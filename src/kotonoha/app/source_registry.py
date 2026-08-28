"""Stateful registry for live source candidates and their clocks."""

from __future__ import annotations

from ..lyrics.models import LyricsDocument
from ..playback.models import PlaybackObservation
from .source_contracts import (
    LiveSourceCandidate,
    LiveSourceTiming,
    SourceClientId,
)


class LiveSourceRegistry:
    """Retain the latest candidate and calibrated timing for each source client."""

    def __init__(self) -> None:
        self._candidates: dict[SourceClientId, tuple[int, LiveSourceCandidate]] = {}
        self._timings: dict[SourceClientId, tuple[int, int | None, LiveSourceTiming]] = {}
        self._sequence = 0
        self._tick_sequence = 0

    @property
    def revision(self) -> int:
        """Return the monotonic candidate revision."""
        return self._sequence

    def observe(
        self,
        client_id: SourceClientId,
        observation: PlaybackObservation,
        document: LyricsDocument | None,
    ) -> tuple[LiveSourceCandidate | None, LiveSourceCandidate]:
        """Replace one client's candidate and return its previous value."""
        retained = self._candidates.get(client_id)
        previous = retained[1] if retained is not None else None
        self._sequence += 1
        candidate = LiveSourceCandidate(client_id, observation, document)
        self._candidates[client_id] = (self._sequence, candidate)
        return previous, candidate

    def observe_clock(
        self,
        client_id: SourceClientId,
        track_ref: str | None,
        current_time: float | None,
        is_playing: bool | None,
    ) -> bool:
        """Retain a clock only when it refers to the latest candidate snapshot."""
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

    def candidate_for(self, client_id: SourceClientId | None) -> LiveSourceCandidate | None:
        """Return one retained candidate without exposing registry storage."""
        retained = self._candidates.get(client_id) if client_id is not None else None
        return retained[1] if retained is not None else None

    def candidate_entry(
        self,
        client_id: SourceClientId,
    ) -> tuple[int, LiveSourceCandidate] | None:
        """Return one candidate together with the revision that created it."""
        return self._candidates.get(client_id)

    def candidate_entries(self) -> tuple[tuple[SourceClientId, tuple[int, LiveSourceCandidate]], ...]:
        """Return an immutable view used by ownership arbitration."""
        return tuple(self._candidates.items())

    def timing_entries(
        self,
    ) -> tuple[tuple[SourceClientId, tuple[int, int | None, LiveSourceTiming]], ...]:
        """Return an immutable view used by timing arbitration."""
        return tuple(self._timings.items())

    def clear_client(self, client_id: SourceClientId) -> LiveSourceCandidate | None:
        """Forget one candidate and any clock tied to its snapshot."""
        self._timings.pop(client_id, None)
        retained = self._candidates.pop(client_id, None)
        if retained is None:
            return None
        self._sequence += 1
        return retained[1]


__all__ = ["LiveSourceRegistry"]
