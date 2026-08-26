"""Qt compatibility publishing for canonical display frames."""

from __future__ import annotations

from ..state import LyricsState
from .models import DisplayFrame


class QtDisplayPublisher:
    """Own the only compatibility write from ``DisplayFrame`` into Qt state."""

    def __init__(self, state: LyricsState) -> None:
        self._state = state

    def publish(self, frame: DisplayFrame) -> bool:
        """Publish one canonical frame, returning whether state changed."""
        return self._state.update(frame)


__all__ = ["QtDisplayPublisher"]
