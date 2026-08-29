"""Shared themed window surface for settings-related Qt dialogs."""

from __future__ import annotations

import logging
from typing import cast

from PyQt6.QtCore import Qt
from PyQt6.QtGui import (
    QCloseEvent,
    QColor,
    QHideEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QShowEvent,
)
from PyQt6.QtWidgets import QDialog, QWidget

from ...config import Config
from ...platform import OverlayPlatform, OverlayPlatformFactory, QtWindowHost, SurfaceResult, WindowRectangle
from . import theme

_RADIUS = 14
logger = logging.getLogger(__name__)


class SettingsTitleBar(QWidget):
    """Provide the shared drag target used by frameless settings windows."""

    def mousePressEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            if window is not None:
                handle = window.windowHandle()
                if handle is not None and handle.startSystemMove():
                    a0.accept()
                    return
        super().mousePressEvent(a0)


class ThemedSettingsDialog(QDialog):
    """Own the shared frameless, translucent, and blur-capable dialog surface."""

    def __init__(
        self,
        config: Config,
        parent: QWidget | None = None,
        *,
        platform_factory: OverlayPlatformFactory | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme._resolve_theme(config.theme)
        self._accent = config.accent_start
        self._platform: OverlayPlatform | None = None
        if platform_factory is not None:
            self._platform = platform_factory(QtWindowHost(self, stay_on_top=False))
        capabilities = self._platform.capabilities if self._platform is not None else None
        self._blur_capable = capabilities is not None and capabilities.blur
        self._blur_reason = capabilities.blur_reason if capabilities is not None else "bridge"
        self._window_opacity_ok = capabilities is None or capabilities.window_opacity
        self._frosted = self._blur_capable and config.frost_window
        self._win_opacity = config.settings_opacity
        # A resize can be delivered while the base widget is being configured;
        # defer virtual style hooks until the concrete dialog owns its fields.
        self._surface_style_ready = False
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def _apply_surface_style(self) -> None:
        """Apply the current content stylesheet supplied by a concrete dialog."""
        raise NotImplementedError

    def _mark_surface_style_ready(self) -> None:
        """Allow platform callbacks to reapply the concrete dialog stylesheet."""
        self._surface_style_ready = True

    def paintEvent(self, a0: QPaintEvent | None) -> None:  # noqa: ARG002
        """Paint the theme-aware rounded window fill behind dialog children."""
        palette = theme._PALETTES[self._theme]
        rgba = cast("dict[str, tuple[int, int, int, int]]", palette)
        bg = rgba["window_bg"]
        if self._frosted:
            bg = (bg[0], bg[1], bg[2], 165)
        else:
            bg = (bg[0], bg[1], bg[2], max(0, min(255, round(255 * self._win_opacity))))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(*bg))
        painter.setPen(QPen(QColor(*rgba["window_border"])))
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.drawRoundedRect(rect, float(_RADIUS), float(_RADIUS))

    def _apply_blur(self) -> None:
        """Apply the compositor blur region and fall back to an opaque surface."""
        if not self._frosted or self._platform is None:
            return
        blur = self._platform.blur
        if blur is None:
            return
        result = blur.set_blur_region(WindowRectangle(0, 0, self.width(), self.height()), _RADIUS)
        if result.succeeded:
            return
        logger.warning("Frosted glass unavailable, falling back to a solid panel: %s", result.reason)
        self._frosted = False
        if self._surface_style_ready:
            self._apply_surface_style()
            self.update()

    def hideEvent(self, a0: QHideEvent | None) -> None:
        """Release the compositor blur region when the dialog is hidden."""
        if self._frosted and self._platform is not None:
            blur = self._platform.blur
            if blur is not None:
                blur.set_blur_region(None)
        super().hideEvent(a0)

    def done(self, a0: int) -> None:
        """Finish the Qt dialog before releasing its native platform surface."""
        super().done(a0)
        surface_result = self._close_platform()
        if not surface_result.succeeded:
            logger.warning("Settings surface shutdown was incomplete: %s", surface_result.reason)

    def closeEvent(self, a0: QCloseEvent | None) -> None:
        """Let QDialog finish and release the platform surface from :meth:`done`."""
        super().closeEvent(a0)

    def _close_platform(self) -> SurfaceResult:
        """Close the optional platform surface and report whether it completed."""
        if self._platform is None:
            return SurfaceResult.applied()
        return self._platform.surface.close()

    def show(self) -> None:
        """Prepare the optional platform surface before Qt maps the window."""
        if self._platform is not None:
            prepared = self._platform.surface.prepare()
            if not prepared.succeeded:
                self._log_surface_failure("preparation", prepared)
        super().show()

    def resizeEvent(self, a0: QResizeEvent | None) -> None:
        """Keep the compositor blur region matched to the current window size."""
        super().resizeEvent(a0)
        self._apply_blur()

    def showEvent(self, a0: QShowEvent | None) -> None:
        """Activate the optional platform surface after the window is mapped."""
        super().showEvent(a0)
        if self._platform is not None:
            activated = self._platform.surface.activate()
            if not activated.succeeded:
                self._log_surface_failure("activation", activated)
        self._apply_blur()

    @staticmethod
    def _log_surface_failure(operation: str, result: SurfaceResult) -> None:
        """Log a non-fatal platform lifecycle failure with its reported reason."""
        logger.warning("Settings surface %s failed: %s", operation, result.reason)


__all__ = ["SettingsTitleBar", "ThemedSettingsDialog"]
