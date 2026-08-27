"""Source-neutral ownership and live-candidate coordination."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, TypeAlias

from ..playback.models import PlaybackObservation
from .match import Candidate, MatchConfidence, TrackMetadata, evaluate_match
from .models import LyricsDocument

SourceClientId: TypeAlias = int | str

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiveSourceCandidate:
    """The latest normalized facts retained for one live source client."""

    client_id: SourceClientId
    observation: PlaybackObservation
    document: LyricsDocument | None
    confidence: MatchConfidence = MatchConfidence.HIGH


@dataclass(frozen=True)
class LiveSourceMatch:
    """A live candidate that matches the currently selected player track."""

    client_id: SourceClientId
    observation: PlaybackObservation
    document: LyricsDocument
    confidence: MatchConfidence


@dataclass(frozen=True)
class LiveSourceTiming:
    """A clock update tied to the candidate snapshot it followed."""

    client_id: SourceClientId
    track_ref: str | None
    current_time: float | None
    is_playing: bool | None
    duration_s: float | None = None


class SourceOwnershipCoordinator:
    """Retain source candidates and bind one source to the display clock."""

    def __init__(self) -> None:
        self._mode: Literal["standalone", "external", "live"] = "standalone"
        self._bound_client_id: SourceClientId | None = None
        self._candidates: dict[SourceClientId, tuple[int, LiveSourceCandidate]] = {}
        self._sequence = 0
        self._timings: dict[SourceClientId, tuple[int, int | None, LiveSourceTiming]] = {}
        self._tick_sequence = 0

    @property
    def live_active(self) -> bool:
        """Whether the bound live source currently has usable lyrics."""
        retained = self._candidate_for(self._bound_client_id)
        return self._mode == "live" and retained is not None and self._has_lyrics(retained)

    @property
    def mode(self) -> Literal["standalone", "external", "live"]:
        """Return the current display ownership mode for diagnostics and adapters."""
        return self._mode

    @property
    def revision(self) -> int:
        """Return the candidate revision used for late-source decisions."""
        return self._sequence

    def select_external(self) -> None:
        """Reserve display ownership for the local player workflow."""
        self._set_mode("external", None)

    def select_live(self, client_id: SourceClientId) -> None:
        """Bind display ownership to one live source client."""
        self._set_mode("live", client_id)

    def select_standalone(self) -> None:
        """Release source ownership so an adapter may publish directly."""
        self._set_mode("standalone", None)

    def observe(
        self,
        client_id: SourceClientId,
        observation: PlaybackObservation,
        document: LyricsDocument | None,
    ) -> None:
        """Retain one normalized source snapshot for matching and arbitration."""
        previous = self._candidates.get(client_id)
        self._sequence += 1
        candidate = LiveSourceCandidate(client_id, observation, document)
        self._candidates[client_id] = (
            self._sequence,
            candidate,
        )
        if previous is None or self._candidate_log_key(previous[1]) != self._candidate_log_key(candidate):
            track = observation.track
            logger.debug(
                "lyrics live candidate updated: client=%r track=%r / %r ref=%r "
                "lyrics=%s provider=%r provider_name=%r lines=%d",
                client_id,
                track.title if track is not None else "",
                track.artist if track is not None else "",
                track.track_ref if track is not None else None,
                document is not None and bool(document.lines),
                document.source_id if document is not None else None,
                document.source_name if document is not None else None,
                len(document.lines) if document is not None else 0,
            )

    def observe_clock(
        self,
        client_id: SourceClientId,
        track_ref: str | None,
        current_time: float | None,
        is_playing: bool | None,
    ) -> bool:
        """Retain a clock only when it refers to the latest source snapshot."""
        retained = self._candidates.get(client_id)
        if retained is None:
            return False
        candidate = retained[1]
        current_track_ref = candidate.observation.track.track_ref if candidate.observation.track else None
        if track_ref != current_track_ref:
            return False
        self._tick_sequence += 1
        self._timings[client_id] = (
            self._tick_sequence,
            retained[0],
            LiveSourceTiming(
                client_id,
                track_ref,
                current_time,
                is_playing,
                candidate.observation.duration_s,
            ),
        )
        return True

    @staticmethod
    def _accepted_confidence(
        candidate: LiveSourceCandidate,
        track: TrackMetadata,
        *,
        require_lyrics: bool,
    ) -> MatchConfidence | None:
        """Return the confidence accepted for a candidate, or ``None``."""
        if require_lyrics and not SourceOwnershipCoordinator._has_lyrics(candidate):
            return None
        metadata = SourceOwnershipCoordinator._track_metadata(candidate)
        if metadata is None or not metadata.title:
            return None
        document = candidate.document
        evidence = evaluate_match(
            Candidate(
                song_id=document.song_id if document is not None and document.song_id else "live",
                title=metadata.title,
                artist=metadata.artist,
                album=metadata.album,
                duration_s=metadata.duration_s,
            ),
            track,
        )
        if evidence.confidence is MatchConfidence.HIGH:
            return MatchConfidence.HIGH
        if evidence.confidence is MatchConfidence.MEDIUM and evidence.title_exact:
            return MatchConfidence.MEDIUM
        return None

    @staticmethod
    def _has_lyrics(candidate: LiveSourceCandidate) -> bool:
        return candidate.document is not None and bool(candidate.document.lines)

    @staticmethod
    def _track_metadata(candidate: LiveSourceCandidate) -> TrackMetadata | None:
        track = candidate.observation.track
        document = candidate.document
        if track is not None:
            return TrackMetadata(track.title, track.artist, track.album, track.duration_s)
        if document is not None and document.title is not None:
            return TrackMetadata(
                document.title,
                document.artist or "",
                document.album or "",
                document.duration_s,
            )
        return None

    def _candidate_for(self, client_id: SourceClientId | None) -> LiveSourceCandidate | None:
        retained = self._candidates.get(client_id) if client_id is not None else None
        return retained[1] if retained is not None else None

    def current_match(self, track: TrackMetadata) -> LiveSourceMatch | None:
        """Return the newest live candidate with usable lyrics for ``track``."""
        ordered = sorted(self._candidates.items(), key=lambda item: item[1][0], reverse=True)
        for client_id, (_sequence, candidate) in ordered:
            confidence = self._accepted_confidence(candidate, track, require_lyrics=True)
            if confidence is not None and candidate.document is not None:
                return LiveSourceMatch(client_id, candidate.observation, candidate.document, confidence)
        return None

    def current_timing(self, track: TrackMetadata) -> LiveSourceTiming | None:
        """Return the newest clock tied to a matching source snapshot."""
        ordered = sorted(self._timings.items(), key=lambda item: item[1][0], reverse=True)
        for client_id, (_tick_sequence, candidate_sequence, timing) in ordered:
            retained = self._candidates.get(client_id)
            if retained is None or retained[0] != candidate_sequence:
                continue
            if self._accepted_confidence(retained[1], track, require_lyrics=False) is not None:
                return timing
        return None

    def accepts(self, client_id: SourceClientId) -> bool:
        """Return whether a source client currently owns display publication."""
        if self._mode == "standalone":
            return True
        if self._mode == "external":
            return False
        return client_id == self._bound_client_id

    def clear_client(self, client_id: SourceClientId) -> None:
        """Forget one source's facts without changing the current ownership mode."""
        self._timings.pop(client_id, None)
        retained = self._candidates.pop(client_id, None)
        if retained is not None:
            self._sequence += 1
            candidate = retained[1]
            track = candidate.observation.track
            logger.info(
                "lyrics live candidate removed: client=%r track=%r / %r ref=%r provider=%r",
                client_id,
                track.title if track is not None else "",
                track.artist if track is not None else "",
                track.track_ref if track is not None else None,
                candidate.document.source_id if candidate.document is not None else None,
            )

    def drop_client(self, client_id: SourceClientId) -> None:
        """Forget a disconnected source and release a binding to it."""
        self.clear_client(client_id)
        if self._bound_client_id == client_id:
            self.select_external()

    def _set_mode(
        self,
        mode: Literal["standalone", "external", "live"],
        client_id: SourceClientId | None,
    ) -> None:
        previous_mode = self._mode
        previous_client = self._bound_client_id
        self._mode = mode
        self._bound_client_id = client_id
        if previous_mode == mode and previous_client == client_id:
            return
        previous = previous_mode if previous_client is None else f"{previous_mode}:{previous_client!r}"
        current = mode if client_id is None else f"{mode}:{client_id!r}"
        logger.info("lyrics display ownership changed: %s -> %s", previous, current)

    @staticmethod
    def _candidate_log_key(candidate: LiveSourceCandidate) -> tuple[object, ...]:
        """Return candidate facts whose change is useful in operational logs."""
        track = candidate.observation.track
        document = candidate.document
        return (
            track.track_ref if track is not None else None,
            track.title if track is not None else "",
            track.artist if track is not None else "",
            document.source_id if document is not None else None,
            document.source_name if document is not None else None,
            len(document.lines) if document is not None else 0,
            document.timing if document is not None else None,
        )


__all__ = [
    "LiveSourceCandidate",
    "LiveSourceMatch",
    "LiveSourceTiming",
    "SourceClientId",
    "SourceOwnershipCoordinator",
]
