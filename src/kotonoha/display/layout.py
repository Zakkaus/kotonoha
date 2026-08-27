"""Pure text-fit decisions shared by the display policy and Qt renderer."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class TextFitDecision:
    """The renderer-independent result of comparing measured and available width."""

    measured_width: float
    available_width: float
    overflow: float

    @property
    def fits(self) -> bool:
        """Return whether the measured text fits without horizontal scrolling."""
        return self.overflow <= 0.0


@dataclass(frozen=True)
class FontFitPolicy:
    """Choose stable window budgets and scrolling decisions without Qt types."""

    min_window_width: int = 1100
    max_screen_fraction: float = 0.9
    font_width_factor: int = 28
    horizontal_padding: int = 56
    min_content_width: int = 200

    def __post_init__(self) -> None:
        """Reject invalid geometry constants at composition time."""
        if self.min_window_width <= 0 or self.font_width_factor <= 0:
            raise ValueError("font fit dimensions must be positive")
        if not 0.0 < self.max_screen_fraction <= 1.0:
            raise ValueError("screen width fraction must be within (0, 1]")
        if self.horizontal_padding < 0 or self.min_content_width <= 0:
            raise ValueError("font fit padding and content width must be non-negative")

    def window_width(self, screen_width: int, font_size: int) -> int:
        """Return a stable fit-mode window width for one screen and font size."""
        if screen_width <= 0 or font_size <= 0:
            raise ValueError("screen width and font size must be positive")
        budget = max(self.min_window_width, font_size * self.font_width_factor)
        return min(max(1, int(screen_width * self.max_screen_fraction)), budget)

    def content_width(self, window_width: int) -> int:
        """Return the lyric width after transparent window padding."""
        if window_width <= 0:
            raise ValueError("window width must be positive")
        return max(self.min_content_width, window_width - self.horizontal_padding)

    def decide(self, measured_width: float, available_width: float) -> TextFitDecision:
        """Return whether a measured line fits and, if not, its overflow."""
        if not math.isfinite(measured_width) or not math.isfinite(available_width):
            raise ValueError("text widths must be finite")
        if measured_width < 0.0 or available_width < 0.0:
            raise ValueError("text widths must be non-negative")
        return TextFitDecision(measured_width, available_width, max(0.0, measured_width - available_width))


__all__ = ["FontFitPolicy", "TextFitDecision"]
