"""Qt publisher for canonical display frames."""

from __future__ import annotations

from ...display.models import DisplayFrame
from .state import LyricsState


class QtDisplayPublisher:
    """Own the only concrete write from ``DisplayFrame`` into Qt state."""

    def __init__(self, state: LyricsState) -> None:
        self._state = state

    def publish(self, frame: DisplayFrame) -> bool:
        """Publish one canonical frame, returning whether state changed."""
        return self._state.update(frame)


__all__ = ["QtDisplayPublisher"]
