"""Qt presentation adapter for the toolkit-neutral overlay window contract."""

from __future__ import annotations

import PyQt6.sip as sip
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtWidgets import QApplication, QWidget

from .overlay_contracts import WindowHost, WindowPoint, WindowPolicy, WindowRectangle


class QtWindowHost(WindowHost):
    """Translate abstract window operations to one top-level Qt widget."""

    def __init__(self, widget: QWidget) -> None:
        self._widget = widget
        self._known_position: WindowPoint | None = None

    def apply_window_policy(self, policy: WindowPolicy) -> None:
        if policy.recreate_surface:
            flags = (
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Window
            )
            if policy.transparent_for_input:
                flags |= Qt.WindowType.WindowTransparentForInput
            if policy.does_not_accept_focus:
                flags |= Qt.WindowType.WindowDoesNotAcceptFocus
            self._widget.setWindowFlags(flags)
        self._widget.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            policy.mouse_events_transparent,
        )
        self._widget.setAttribute(
            Qt.WidgetAttribute.WA_ShowWithoutActivating,
            policy.show_without_activating,
        )

    def native_window_pointer(self) -> int | None:
        self._widget.winId()
        handle = self._widget.windowHandle()
        if handle is None:
            return None
        try:
            pointer = sip.unwrapinstance(handle)
        except (RuntimeError, TypeError):
            return None
        return int(pointer) if pointer is not None else None

    def geometry(self) -> WindowRectangle:
        return self._rectangle(self._widget.geometry())

    def window_position(self) -> WindowPoint | None:
        if self._known_position is not None:
            return self._known_position
        geometry = self._widget.geometry()
        return WindowPoint(geometry.x(), geometry.y())

    def screen_geometry(self) -> WindowRectangle | None:
        handle = self._widget.windowHandle()
        screen = handle.screen() if handle is not None else QApplication.primaryScreen()
        return self._rectangle(screen.geometry()) if screen is not None else None

    def bind_output(self, output: WindowRectangle) -> None:
        for screen in QApplication.screens():
            if self._rectangle(screen.geometry()) == output:
                self._widget.setScreen(screen)
                handle = self._widget.windowHandle()
                if handle is not None:
                    handle.setScreen(screen)
                return
        raise RuntimeError("Requested output is not available.")

    def move_window(self, position: WindowPoint) -> None:
        self._known_position = position
        self._widget.move(position.x, position.y)

    def refresh(self) -> None:
        self._widget.update()

    @staticmethod
    def _rectangle(rectangle: QRect) -> WindowRectangle:
        return WindowRectangle(
            rectangle.x(), rectangle.y(), rectangle.width(), rectangle.height()
        )
