"""Timeline selectors and canonical display-frame projection."""

# TODO(phase-6): remove this compatibility module after all callers migrate to
# ``display.presentation`` and ``display.rules`` directly.

from __future__ import annotations

from ..display.models import DisplayFrame
from ..display.presentation import DisplayEngine
from ..display.rules import (
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
) -> DisplayFrame:
    """Project one document through the shared presentation adapter."""
    return DisplayEngine().project(
        document,
        position,
        track=track,
        is_playing=is_playing,
    )
