"""Pure temporal progress rules used by the display projection."""

from __future__ import annotations

import math

from ..lyrics.models import LyricLine, LyricWord
from .models import Interlude


def _clamp01(value: float) -> float:
    """Clamp a temporal fraction to the renderer's ``0..1`` contract."""
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    return value


def line_fill_fraction(start: float, end: float, position: float) -> float:
    """Return the fraction of a timed span completed at ``position``."""
    if end <= start:
        return 1.0 if position >= end else 0.0
    return _clamp01((position - start) / (end - start))


def word_fill_fraction(word: LyricWord, position: float) -> float:
    """Return the fraction of a timed word completed at ``position``."""
    if word.start is None or word.end is None:
        return 0.0
    return line_fill_fraction(word.start, word.end, position)


def word_fill_fractions(words: tuple[LyricWord, ...], position: float) -> tuple[float, ...]:
    """Return progress for words in their canonical document order."""
    return tuple(word_fill_fraction(word, position) for word in words)


def active_word_index(words: tuple[LyricWord, ...], position: float) -> int:
    """Return the currently sung word, or the last completed word."""
    last_started = -1
    for index, word in enumerate(words):
        fraction = word_fill_fraction(word, position)
        if 0.0 < fraction < 1.0:
            return index
        if fraction >= 1.0:
            last_started = index
    return last_started


def line_progress(line: LyricLine, position: float) -> float:
    """Return overall line progress, preferring complete word timing."""
    if line.has_word_timing and line.words:
        first = next(
            (word for word in line.words if word.start is not None and word.end is not None),
            None,
        )
        if first is not None:
            last = next(
                (word for word in reversed(line.words) if word.start is not None and word.end is not None),
                first,
            )
            first_start = first.start if first.start is not None else line.start
            last_end = last.end if last.end is not None else line.end
            return line_fill_fraction(first_start, last_end, position)
    return line_fill_fraction(line.start, line.end, position)


_INTERLUDE_DOTS = "\u25cf\u2003\u25cf\u2003\u25cf"
_STILL_NOTE = "\u266a"


def interlude_text(interlude: Interlude, position: float, *, style: str, countdown: str) -> str:
    """Format the semantic interlude marker for the current renderer."""
    indicator = _STILL_NOTE if style == "symbol" else _INTERLUDE_DOTS
    if countdown == "percent":
        return f"{indicator}\u2003\u2003{round(interlude.progress(position) * 100)}%"
    if countdown == "seconds":
        return f"{indicator}\u2003\u2003{max(0, math.ceil(interlude.end - position))}s"
    return indicator
