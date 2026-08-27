"""Stateless lyric projection rules owned by the display domain."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from statistics import median

from ..lyrics.models import LyricLine
from .models import Interlude

_INTERLUDE_FACTOR = 2.5
_INTERLUDE_FLOOR_S = 12.0
_SWEEP_CAP_FACTOR = 2.0


def find_current_index(lines: Sequence[LyricLine], position: float) -> int:
    """Return the last line whose start is not after ``position``."""
    index = -1
    for index_candidate, line in enumerate(lines):
        if line.start <= position:
            index = index_candidate
        else:
            break
    return index


def typical_span(lines: Sequence[LyricLine]) -> float:
    """Return the median positive distance between neighboring line starts."""
    spans = [lines[index + 1].start - lines[index].start for index in range(len(lines) - 1)]
    usable = [span for span in spans if span > 0.0]
    return median(usable) if usable else 0.0


def in_interlude(
    lines: Sequence[LyricLine], index: int, position: float, duration_s: float | None = None
) -> bool:
    """Return whether ``position`` is in an instrumental gap after ``index``."""
    if not 0 <= index < len(lines):
        return False
    line = lines[index]
    if index + 1 == len(lines):
        return duration_s is not None and duration_s > line.end and position > line.end
    span = lines[index + 1].start - line.start
    typical = typical_span(lines)
    if typical <= 0.0 or span <= _INTERLUDE_FACTOR * typical or span < _INTERLUDE_FLOOR_S:
        return False
    return position > line.start + typical


def interlude_at(
    lines: Sequence[LyricLine], index: int, position: float, duration_s: float | None = None
) -> Interlude | None:
    """Return the active intro, instrumental, or outro gap."""
    if not lines:
        return None
    if index < 0:
        return Interlude(0.0, lines[0].start) if position < lines[0].start else None
    if not in_interlude(lines, index, position, duration_s):
        return None
    line = lines[index]
    if index + 1 == len(lines):
        if duration_s is None or duration_s <= line.end:
            return None
        return Interlude(line.end, duration_s)
    return Interlude(line.start + typical_span(lines), lines[index + 1].start)


def sweep_end(line: LyricLine, typical: float) -> float:
    """Return the visual sweep end without changing the canonical lyric line."""
    if line.has_word_timing:
        sung = max((word.end for word in line.words if word.end is not None), default=None)
        return line.end if sung is None or sung >= line.end else sung
    if typical <= 0.0:
        return line.end
    return min(line.end, line.start + _SWEEP_CAP_FACTOR * typical)


def swept_line(line: LyricLine, typical: float) -> LyricLine:
    """Compatibility projection for callers that still expect a shortened line.

    DisplayEngine itself never uses this helper; it returns a separate progress
    value so the canonical document line remains unchanged.
    """
    end = sweep_end(line, typical)
    return line if end == line.end else replace(line, end=end)


def song_timing(lines: Sequence[LyricLine]) -> str:
    """Return the legacy timing label for a line collection."""
    return "Word" if any(line.has_word_timing for line in lines) else "Line"


__all__ = [
    "find_current_index",
    "in_interlude",
    "interlude_at",
    "song_timing",
    "sweep_end",
    "swept_line",
    "typical_span",
]
