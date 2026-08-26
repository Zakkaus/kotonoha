"""MPRIS position normalization for players with cumulative timelines."""

from __future__ import annotations

import logging
import time

from ..lyrics.models import LyricLine
from .mpris_track import TrackCommit

logger = logging.getLogger(__name__)


class MprisTimeline:
    """Track song-relative offset and correct stale transition positions."""

    def __init__(self) -> None:
        self._offset = 0.0
        self._calibration_generation: int | None = None
        self._calibration_until = 0.0
        self._calibration_offset: float | None = None

    @property
    def offset(self) -> float:
        """Return the offset subtracted from raw player position."""
        return self._offset

    def observe_commit(self, commit: TrackCommit) -> None:
        """Adopt a transition start position and open its correction window."""
        if commit.start_position is None:
            return
        self._offset = commit.start_position
        if commit.start_position > 0.0:
            self._calibration_generation = commit.generation
            self._calibration_until = time.monotonic() + 2.0
            self._calibration_offset = commit.start_position
        else:
            self._calibration_generation = None
            self._calibration_offset = None

    def calibrate(self, commit: TrackCommit, raw_position: float, observed_at: float) -> bool:
        """Reset a stale transition offset when the player reports a rewind."""
        if (
            self._calibration_generation != commit.generation
            or observed_at > self._calibration_until
            or self._calibration_offset is None
            or raw_position >= self._calibration_offset - 0.5
        ):
            return False
        logger.debug(
            "MPRIS calibration: offset %.3fs -> 0.0 (raw %.3fs, gen %d)",
            self._calibration_offset,
            raw_position,
            commit.generation,
        )
        self._offset = 0.0
        self._calibration_generation = None
        self._calibration_offset = None
        return True

    def reconcile(
        self,
        commit: TrackCommit,
        lines: tuple[LyricLine, ...],
        song_length: float | None,
        raw_position: float | None,
    ) -> None:
        """Infer a cumulative position offset from the resolved lyric timeline."""
        if self._offset != 0.0 or not lines or raw_position is None or raw_position <= lines[-1].end:
            return
        claimed = commit.info.length_s
        if claimed is None or claimed <= lines[-1].end:
            logger.info(
                "MPRIS position %.0fs is past the last line at %.0fs and the reported "
                "length cannot say by how much; leaving the song unplaced",
                raw_position,
                lines[-1].end,
            )
            return
        actual = song_length if song_length is not None and song_length > lines[-1].end else lines[-1].end
        self._offset = claimed - actual
        logger.info(
            "MPRIS reports %.0fs of %.0fs for a %.0fs song; treating both as running "
            "totals and shifting by %.0fs",
            raw_position,
            claimed,
            actual,
            self._offset,
        )

    def reset(self) -> None:
        """Clear all position correction state."""
        self._offset = 0.0
        self._calibration_generation = None
        self._calibration_until = 0.0
        self._calibration_offset = None


__all__ = ["MprisTimeline"]
