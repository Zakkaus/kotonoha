"""Shared canonical display state with Qt change notification."""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal

from .display.models import EMPTY_FRAME, DisplayFrame


class LyricsState(QObject):
    frame_changed = pyqtSignal(object)  # emits DisplayFrame when display content changes

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._frame: DisplayFrame = EMPTY_FRAME

    @property
    def frame(self) -> DisplayFrame:
        """Return the latest canonical frame owned by the application."""
        return self._frame

    def update(self, frame: DisplayFrame) -> bool:
        """Store ``frame`` and notify listeners if it changed.

        Returns True if the frame differed and a signal was emitted.
        """
        if frame == self._frame:
            return False
        self._frame = frame
        self.frame_changed.emit(frame)
        return True

    def clear(self) -> bool:
        return self.update(EMPTY_FRAME)
