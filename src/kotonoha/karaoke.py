"""Compatibility exports for the display karaoke rules.

TODO(phase-6): remove this module after UI and tests import ``display.karaoke``
directly.  The implementation now belongs to the display package.
"""

from .display.karaoke import (
    active_word_index,
    interlude_text,
    line_fill_fraction,
    line_progress,
    word_fill_fraction,
    word_fill_fractions,
)

__all__ = [
    "active_word_index",
    "interlude_text",
    "line_fill_fraction",
    "line_progress",
    "word_fill_fraction",
    "word_fill_fractions",
]
