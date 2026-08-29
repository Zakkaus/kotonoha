"""Source-neutral ownership and live-candidate coordination."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Literal

from ..config import DEFAULT_DISPLAY_SOURCES, VALID_DISPLAY_SOURCES
from ..lyrics.live_contracts import LiveSourceMatch
from ..lyrics.match import TrackMetadata
from ..lyrics.models import LyricsDocument
from ..playback.models import PlaybackObservation, PlaybackStatus
from .source_contracts import (
    LiveSourceCandidate,
    LiveSourceTiming,
    SourceClientId,
)
from .source_matching import accepted_confidence, has_lyrics
from .source_registry import LiveSourceRegistry

logger = logging.getLogger(__name__)


class SourceOwnershipCoordinator:
    """Retain source candidates and bind one source to the display clock."""

    def __init__(self, display_sources: Sequence[str] | None = None) -> None:
        self._mode: Literal["standalone", "external", "live"] = "standalone"
        self._bound_client_id: SourceClientId | None = None
        self._registry = LiveSourceRegistry()
        self._display_sources = self._normalize_display_sources(display_sources)

    @property
    def live_active(self) -> bool:
        """Whether the bound live source currently has usable lyrics."""
        retained = self._candidate_for(self._bound_client_id)
        return self._mode == "live" and retained is not None and has_lyrics(retained)

    @property
    def mode(self) -> Literal["standalone", "external", "live"]:
        """Return the current display ownership mode for diagnostics and adapters."""
        return self._mode

    @property
    def revision(self) -> int:
        """Return the candidate revision used for late-source decisions."""
        return self._registry.revision

    @property
    def display_sources(self) -> tuple[str, ...]:
        """Return enabled display source slots in their configured priority order."""
        return self._display_sources

    def set_display_sources(self, sources: Sequence[str]) -> None:
        """Apply source priority and re-elect a standalone owner when needed."""
        updated = self._normalize_display_sources(sources)
        if updated == self._display_sources:
            return
        self._display_sources = updated
        if self._mode == "external" and not self._source_enabled("mpris"):
            self.select_standalone()
        elif self._mode == "live" and not self._source_enabled_for_client(self._bound_client_id):
            self.select_standalone()
        elif self._mode == "standalone":
            self._elect_standalone_owner()

    def select_external(self) -> bool:
        """Reserve display ownership for the local player workflow."""
        if not self._source_enabled("mpris"):
            self.select_standalone()
            return False
        self._set_mode("external", "mpris")
        return True

    def select_live(self, client_id: SourceClientId) -> bool:
        """Bind display ownership to one live source client."""
        if not self._source_enabled_for_client(client_id):
            self.select_standalone()
            return False
        self._set_mode("live", client_id)
        return True

    def select_standalone(self) -> None:
        """Release source ownership so an adapter may publish directly."""
        self._set_mode("standalone", None)
        self._elect_standalone_owner()

    def observe(
        self,
        client_id: SourceClientId,
        observation: PlaybackObservation,
        document: LyricsDocument | None,
    ) -> None:
        """Retain one normalized source snapshot for matching and arbitration."""
        previous, candidate = self._registry.observe(client_id, observation, document)
        if self._mode == "standalone":
            self._elect_standalone_owner()
        if previous is None or self._candidate_log_key(previous) != self._candidate_log_key(candidate):
            track = observation.track
            logger.debug(
                "live lyric candidate updated: adapter=%r track=%r artist=%r ref=%r "
                "lyric_source=%r source_id=%r lines=%d",
                client_id,
                track.title if track is not None else "",
                track.artist if track is not None else "",
                track.track_ref if track is not None else None,
                _lyric_source_label(document),
                document.source_id if document is not None else None,
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
        return self._registry.observe_clock(client_id, track_ref, current_time, is_playing)

    def _candidate_for(self, client_id: SourceClientId | None) -> LiveSourceCandidate | None:
        return self._registry.candidate_for(client_id)

    def current_match(self, track: TrackMetadata) -> LiveSourceMatch | None:
        """Return the highest-priority matching candidate, newest within its source."""
        ordered = self._ordered_candidates(require_lyrics=True)
        for client_id, (_sequence, candidate) in ordered:
            confidence = accepted_confidence(candidate, track, require_lyrics=True)
            if confidence is not None and candidate.document is not None:
                return LiveSourceMatch(client_id, candidate.observation, candidate.document, confidence)
        return None

    def current_timing(self, track: TrackMetadata) -> LiveSourceTiming | None:
        """Return the newest clock tied to a matching source snapshot."""
        ordered = sorted(
            self._registry.timing_entries(),
            key=lambda item: (
                self._source_priority(item[0]),
                -item[1][0],
            ),
        )
        for client_id, (_tick_sequence, candidate_sequence, timing) in ordered:
            if not self._source_enabled_for_client(client_id):
                continue
            retained = self._registry.candidate_entry(client_id)
            if retained is None or retained[0] != candidate_sequence:
                continue
            if accepted_confidence(retained[1], track, require_lyrics=False) is not None:
                return timing
        return None

    def accepts(self, client_id: SourceClientId) -> bool:
        """Return whether a source client currently owns display publication."""
        if self._mode == "standalone":
            self._elect_standalone_owner()
            return client_id == self._bound_client_id and self._source_enabled_for_client(client_id)
        if self._mode == "external":
            return client_id == "mpris" and self._source_enabled("mpris")
        return client_id == self._bound_client_id and self._source_enabled_for_client(client_id)

    def clear_client(self, client_id: SourceClientId) -> None:
        """Forget one source's facts without changing the current ownership mode."""
        candidate = self._registry.clear_client(client_id)
        if candidate is not None:
            track = candidate.observation.track
            logger.debug(
                "live lyric candidate removed: adapter=%r track=%r artist=%r ref=%r "
                "lyric_source=%r source_id=%r",
                client_id,
                track.title if track is not None else "",
                track.artist if track is not None else "",
                track.track_ref if track is not None else None,
                _lyric_source_label(candidate.document),
                candidate.document.source_id if candidate.document is not None else None,
            )
        if self._mode == "standalone":
            self._elect_standalone_owner()

    def drop_client(self, client_id: SourceClientId) -> None:
        """Forget a disconnected source and release a binding to it."""
        mode = self._mode
        was_bound = self._bound_client_id == client_id
        self.clear_client(client_id)
        if was_bound and mode == "live":
            self.select_external()
        elif mode == "standalone":
            self._elect_standalone_owner()

    def _elect_standalone_owner(self) -> None:
        """Choose one active candidate using source priority and freshness."""
        ordered = self._ordered_candidates(require_lyrics=True)
        if not ordered:
            ordered = self._ordered_candidates(require_lyrics=False)
        owner = ordered[0][0] if ordered else None
        self._set_mode("standalone", owner)

    def _ordered_candidates(
        self,
        *,
        require_lyrics: bool,
    ) -> list[tuple[SourceClientId, tuple[int, LiveSourceCandidate]]]:
        candidates: list[tuple[SourceClientId, tuple[int, LiveSourceCandidate]]] = []
        for client_id, retained in self._registry.candidate_entries():
            candidate = retained[1]
            if not self._source_enabled_for_client(client_id):
                continue
            if candidate.observation.status is PlaybackStatus.STOPPED:
                continue
            if require_lyrics and not has_lyrics(candidate):
                continue
            candidates.append((client_id, retained))
        return sorted(
            candidates,
            key=lambda item: (
                self._source_priority(item[0]),
                -item[1][0],
            ),
        )

    def _source_enabled_for_client(self, client_id: SourceClientId | None) -> bool:
        if client_id is None:
            return False
        return self._source_enabled(self._source_id(client_id))

    def _source_enabled(self, source_id: str) -> bool:
        return source_id in self._display_sources

    def _source_priority(self, client_id: SourceClientId) -> int:
        source_id = self._source_id(client_id)
        try:
            return self._display_sources.index(source_id)
        except ValueError:
            return len(self._display_sources)

    def _source_id(self, client_id: SourceClientId) -> str:
        candidate = self._candidate_for(client_id)
        if candidate is not None and candidate.observation.adapter_id in VALID_DISPLAY_SOURCES:
            return candidate.observation.adapter_id
        if client_id == "cider-api":
            return "cider"
        if client_id == "mpris":
            return "mpris"
        return "adapter"

    @staticmethod
    def _normalize_display_sources(sources: Sequence[str] | None) -> tuple[str, ...]:
        selected = DEFAULT_DISPLAY_SOURCES if sources is None else sources
        normalized: list[str] = []
        for source in selected:
            if source in VALID_DISPLAY_SOURCES and source not in normalized:
                normalized.append(source)
        if not normalized:
            normalized.extend(DEFAULT_DISPLAY_SOURCES)
        return tuple(normalized)

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
        logger.info("lyrics display owner changed: previous=%s current=%s", previous, current)

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

def _lyric_source_label(document: LyricsDocument | None) -> str:
    """Return the human-facing source name used in candidate diagnostics."""
    if document is None:
        return "none"
    return document.source_name if document.source_name is not None else document.source_id


__all__ = [
    "LiveSourceCandidate",
    "LiveSourceTiming",
    "SourceClientId",
    "SourceOwnershipCoordinator",
]
