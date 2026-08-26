"""Presentation facts produced from canonical playback and lyric documents."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..lyrics.models import LyricLine, LyricsDocument
from ..playback.models import TrackIdentity


class DisplayState(StrEnum):
    """The externally meaningful lyric resolution states."""

    NO_TRACK = "NoTrack"
    RESOLVING = "Resolving"
    LYRICS_AVAILABLE = "LyricsAvailable"
    LYRICS_NOT_FOUND = "LyricsNotFound"


@dataclass(frozen=True)
class Interlude:
    """A timed gap in which a lyric document has no active sung line."""

    start: float
    end: float

    def progress(self, position: float) -> float:
        """Return the clamped progress through this gap."""
        span = self.end - self.start
        if span <= 0.0:
            return 1.0
        return min(1.0, max(0.0, (position - self.start) / span))


@dataclass(frozen=True)
class DisplayDiagnostic:
    """A user-visible or loggable explanation attached to a display frame."""

    code: str
    message: str


@dataclass(frozen=True)
class DisplayFrame:
    """The single source-neutral presentation result consumed by a renderer."""

    state: DisplayState
    track: TrackIdentity | None = None
    document: LyricsDocument | None = None
    current_time: float | None = None
    is_playing: bool = False
    previous: LyricLine | None = None
    current: LyricLine | None = None
    next: LyricLine | None = None
    around: tuple[LyricLine, ...] = ()
    interlude: Interlude | None = None
    word_progress: tuple[float, ...] | None = None
    diagnostic: DisplayDiagnostic | None = None


EMPTY_FRAME = DisplayFrame(state=DisplayState.NO_TRACK)
