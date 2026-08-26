"""Timeline selectors and canonical display-frame projection."""

# TODO(phase-6): remove this compatibility module after all callers migrate to
# ``display.presentation`` and ``display.timeline`` directly.

from __future__ import annotations

from ..display.models import DisplayFrame, DisplayState
from ..display.presentation import LyricsPresentationAdapter
from ..display.timeline import (
    find_current_index,
    in_interlude,
    interlude_at,
    song_timing,
    swept_line,
    typical_span,
)
from ..playback.models import TrackIdentity
from .models import LyricsDocument

__all__ = [
    "build_frame",
    "find_current_index",
    "in_interlude",
    "interlude_at",
    "song_timing",
    "swept_line",
    "typical_span",
]


def build_frame(
    document: LyricsDocument | None,
    position: float | None,
    *,
    track: TrackIdentity | None = None,
    is_playing: bool,
    state: DisplayState | None = None,
) -> DisplayFrame:
    """Project one document through the shared presentation adapter."""
    return LyricsPresentationAdapter().project(
        document,
        position,
        track=track,
        is_playing=is_playing,
        state=state,
    )
