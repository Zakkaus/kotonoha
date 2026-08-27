"""Platform-owned surface lifecycle, placement, and drag state for the overlay."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QScreen
from PyQt6.QtWidgets import QApplication, QWidget

from .config import Config
from .overlay_drag import DragRelease, OverlayDragController
from .overlay_geometry import OverlayGeometry, ScreenLike
from .platform.overlay_contracts import (
    DragMode,
    LayerShellBridge,
    Output,
    OverlayOperationResult,
    OverlayPlatform,
    OverlayPlatformFactory,
    WindowPoint,
    WindowPolicy,
    WindowRectangle,
)
from .platform.qt_host import QtWindowHost

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class PositionCommit:
    """Output-local placement persisted after a drag."""

    margin_edge: int
    margin_x: int
    screen_name: str


class OverlaySurfaceController:
    """Own the platform adapter and all geometry state outside the Qt view."""

    def __init__(
        self,
        widget: QWidget,
        config: Config,
        *,
        controller: LayerShellBridge,
        platform_factory: OverlayPlatformFactory,
        band_height: Callable[[], int],
        container_geometry: Callable[[], QRect],
    ) -> None:
        """Create the surface owner without registering screen callbacks."""
        self._widget = widget
        self._config = config
        self._band_height = band_height
        self._container_geometry = container_geometry
        self._geometry = OverlayGeometry(config, band_height)
        self._layer_pos = QPoint()
        self._active_screen: ScreenLike | None = None
        self._preserve_layer_pos_on_show = False
        self._passthrough = config.passthrough
        self._controller = controller
        self._host = QtWindowHost(widget)
        self._platform: OverlayPlatform = platform_factory(self._host)
        self._drag = OverlayDragController(self._platform)
        self._prepare()

    @property
    def controller(self) -> LayerShellBridge:
        """Return the bridge controller owned by this surface."""
        return self._controller

    @property
    def host(self) -> QtWindowHost:
        """Return the Qt host adapter owned by this surface."""
        return self._host

    @property
    def platform(self) -> OverlayPlatform:
        """Return the selected platform adapter."""
        return self._platform

    @platform.setter
    def platform(self, value: OverlayPlatform) -> None:
        """Replace the adapter at the explicit test/compatibility boundary."""
        self._platform = value
        self._drag.platform = value

    @property
    def layer_pos(self) -> QPoint:
        """Return the screen-local top-left position of the surface."""
        return self._layer_pos

    @layer_pos.setter
    def layer_pos(self, value: QPoint) -> None:
        self._layer_pos = value

    @property
    def active_screen(self) -> ScreenLike | None:
        """Return the output currently associated with the surface."""
        return self._active_screen

    @active_screen.setter
    def active_screen(self, value: ScreenLike | None) -> None:
        self._active_screen = value

    @property
    def dragging(self) -> bool:
        """Whether a manual drag gesture is active."""
        return self._drag.dragging

    @dragging.setter
    def dragging(self, value: bool) -> None:
        self._drag.dragging = value

    @property
    def drag_moved(self) -> bool:
        """Whether the active gesture changed the requested position."""
        return self._drag.moved

    @drag_moved.setter
    def drag_moved(self, value: bool) -> None:
        self._drag.moved = value

    @property
    def drag_applied(self) -> bool:
        """Whether every requested movement was accepted by the platform."""
        return self._drag.applied

    @drag_applied.setter
    def drag_applied(self, value: bool) -> None:
        self._drag.applied = value

    @property
    def drag_local(self) -> QPoint:
        """Return the last pointer position in widget coordinates."""
        return self._drag.local

    @drag_local.setter
    def drag_local(self, value: QPoint) -> None:
        self._drag.local = value

    def update_config(self, config: Config) -> None:
        """Use the current placement and platform settings for later operations."""
        self._config = config
        self._geometry.update_config(config)

    def prepare(self) -> None:
        """Prepare the platform surface and apply its non-activating policy."""
        self._prepare()

    def set_output_handler(self, handler: Callable[[Output], bool]) -> None:
        """Register the callback used when a disconnected output returns."""
        self._platform.set_output_handler(handler)

    def _prepare(self) -> None:
        result = self._platform.prepare()
        if not result.succeeded:
            logger.warning("Overlay surface preparation failed: %s", result.reason or "unknown reason")
        self._host.apply_window_policy(WindowPolicy(does_not_accept_focus=True, recreate_surface=True))
        capabilities = self._platform.capabilities
        unavailable = (
            ("layer shell", capabilities.layer_shell, capabilities.layer_shell_reason),
            ("blur", capabilities.blur, capabilities.blur_reason),
            ("input regions", capabilities.input_region, capabilities.input_region_reason),
            ("output rebinding", capabilities.output_rebinding, capabilities.output_rebinding_reason),
        )
        for name, available, reason in unavailable:
            if not available:
                logger.warning("Overlay %s unavailable: %s", name, reason or "no reason provided")

    def configured_screen(self, screens: Sequence[ScreenLike]) -> ScreenLike | None:
        """Find the configured output among the currently reported screens."""
        return self._geometry.configured_screen(screens)

    def set_active_screen(self, screen: ScreenLike | None) -> None:
        """Record the active screen and update the platform output binding."""
        self._active_screen = screen
        self._platform.set_active_output(self._geometry.output(screen))

    def target_screen(
        self,
        screens: Sequence[ScreenLike],
        *,
        configured: ScreenLike | None,
        widget_screen: ScreenLike | None,
        primary: ScreenLike | None,
    ) -> ScreenLike | None:
        """Choose a usable output using active, configured, widget, and primary order."""
        screen = self._geometry.target_screen(
            screens,
            active=self._active_screen,
            configured=configured,
            widget_screen=widget_screen,
            primary=primary,
        )
        if screen is not self._active_screen:
            self.set_active_screen(screen)
        return screen

    @staticmethod
    def usable_screen(screen: ScreenLike | None) -> ScreenLike | None:
        """Return a screen with non-empty geometry, tolerating deleted Qt objects."""
        return OverlayGeometry.usable_screen(screen)

    @staticmethod
    def output(screen: ScreenLike | None) -> Output | None:
        """Convert a toolkit screen into the platform output contract."""
        return OverlayGeometry.output(screen)

    def connected_outputs(self, screens: Sequence[ScreenLike]) -> tuple[Output, ...]:
        """Return all usable outputs currently reported by Qt."""
        return self._geometry.connected_outputs(screens)

    def screen_removed(self, screen: ScreenLike, screens: Sequence[ScreenLike]) -> None:
        """Forward a removed output to the platform lifecycle."""
        output = self.output(screen)
        if output is not None:
            self._platform.output_removed(
                output,
                self.connected_outputs(screens),
                self._config.screen_name or None,
            )

    def screen_added(self, screens: Sequence[ScreenLike]) -> None:
        """Forward a newly available output to the platform lifecycle."""
        if self.connected_outputs(screens):
            self._platform.output_added(self.connected_outputs(screens), self._config.screen_name or None)

    def restore_output(
        self,
        output: Output,
        screens: Sequence[ScreenLike],
        *,
        activate: Callable[[], bool],
        show: Callable[[], None],
    ) -> bool:
        """Rebind and remap a returning output using its current geometry."""
        screen = next((candidate for candidate in screens if candidate.name() == output.name), None)
        if screen is None:
            return False
        self.set_active_screen(screen)
        self.bind_widget_screen(screen)
        self.apply_window_geometry(screens, reset_position=True)
        self._preserve_layer_pos_on_show = True
        rebuilt = activate()
        show()
        return rebuilt

    @staticmethod
    def same_screen(first: ScreenLike | None, second: ScreenLike | None) -> bool:
        """Compare screen identity and geometry without relying on object identity."""
        return OverlayGeometry.same_screen(first, second)

    @staticmethod
    def screen_for_global_point(
        point: QPoint,
        screens: Sequence[ScreenLike],
        fallback: ScreenLike | None,
    ) -> ScreenLike | None:
        """Find the output under a point, or the nearest output across a layout gap."""
        return OverlayGeometry.screen_for_global_point(point, screens, fallback)

    def window_size(self, screen: ScreenLike | None) -> tuple[int, int]:
        """Return the stable surface dimensions for the current output and config."""
        return self._geometry.window_size(screen)

    def compute_layer_pos(
        self,
        width: int,
        height: int,
        screen: ScreenLike | None,
    ) -> QPoint:
        """Compute and clamp the configured screen-local position."""
        return self._geometry.compute_layer_pos(width, height, screen)

    def apply_window_geometry(self, screens: Sequence[ScreenLike], *, reset_position: bool = True) -> None:
        """Size the widget and position it through the selected platform path."""
        screen = self.target_screen(
            screens,
            configured=self.configured_screen(screens),
            widget_screen=self._widget.screen(),
            primary=QApplication.primaryScreen(),
        )
        if screen is None:
            return
        width, height = self.window_size(screen)
        self._widget.setFixedSize(width, height)
        self.bind_widget_screen(screen)
        if reset_position:
            self._layer_pos = self.compute_layer_pos(width, height, screen)
        if not self._platform.capabilities.layer_shell:
            geometry = screen.geometry()
            self._platform.move_to(WindowPoint(geometry.x() + self._layer_pos.x(), geometry.y() + self._layer_pos.y()))

    def bind_widget_screen(self, screen: ScreenLike | None) -> None:
        """Bind both Qt window objects to the selected screen when possible."""
        if screen is None:
            return
        if isinstance(screen, QScreen):
            self._widget.setScreen(screen)
        handle = self._widget.windowHandle()
        if handle is not None and isinstance(screen, QScreen):
            handle.setScreen(screen)

    def activate(
        self,
        screens: Sequence[ScreenLike],
        *,
        fallback: Callable[[], None] | None = None,
    ) -> bool:
        """Activate Layer Shell or use the ordinary-window fallback."""
        screen = self.target_screen(
            screens,
            configured=self.configured_screen(screens),
            widget_screen=self._widget.screen(),
            primary=QApplication.primaryScreen(),
        )
        self.bind_widget_screen(screen)
        result = self._platform.activate()
        capabilities = self._platform.capabilities
        if capabilities.layer_shell and result.succeeded:
            placement = self._platform.move_to(WindowPoint(self._layer_pos.x(), self._layer_pos.y()))
            if not placement.succeeded:
                logger.warning("Layer Shell placement failed: %s", placement.reason or "no reason given")
            self.apply_input_region()
            self.apply_blur()
            return True
        if capabilities.layer_shell:
            logger.warning("Layer Shell activation failed: %s", result.reason or "no reason given")
        if fallback is None:
            self.fallback_position(screen)
        else:
            fallback()
        self.apply_input_region()
        return False

    def fallback_position(self, screen: ScreenLike | None) -> None:
        """Position an ordinary window through the host adapter."""
        if screen is None:
            return
        geometry = screen.geometry()
        position = WindowPoint(geometry.x() + self._layer_pos.x(), geometry.y() + self._layer_pos.y())
        try:
            self._host.move_window(position)
        except RuntimeError as exc:
            logger.debug("Ordinary-window positioning failed: %s", exc)

    def set_passthrough(self, enabled: bool) -> None:
        """Store the click-through setting used by the next input-region pass."""
        self._passthrough = enabled

    def apply_input_region(self) -> None:
        """Apply the visible pill region or full click-through to the platform."""
        if self._passthrough:
            self._platform.set_input_region(None)
            return
        rect = self._container_geometry()
        self._platform.set_input_region(WindowRectangle(rect.x(), rect.y(), rect.width(), rect.height()))

    def set_input_mode(self, passthrough: bool) -> None:
        """Set the input mode owned by this surface before applying its region."""
        self._passthrough = passthrough
        self.apply_input_region()

    def apply_blur(self) -> None:
        """Apply frosted-panel blur when the selected platform supports it."""
        if not self._platform.capabilities.blur:
            return
        if self._config.panel_style == "frost":
            rect = self._container_geometry()
            self._platform.set_blur_region(WindowRectangle(rect.x(), rect.y(), rect.width(), rect.height()), 16)
        else:
            self._platform.set_blur_region(None)

    def begin_drag(self, local: QPoint, global_position: QPoint) -> DragMode:
        """Start a manual drag and retain the initial pointer position."""
        return self._drag.begin(local, global_position)

    def update_drag(self, local: QPoint, global_position: QPoint) -> OverlayOperationResult:
        """Apply one incremental drag delta and retain platform failure state."""
        updated_position, result = self._drag.update(self._layer_pos, local, global_position)
        self._layer_pos = updated_position
        return result

    def end_drag(self) -> DragRelease:
        """End the gesture and state whether persistence is safe."""
        return self._drag.end()

    def clamp_to_screen(
        self,
        pos: QPoint,
        *,
        screen: ScreenLike | None,
        width: int,
        height: int,
        allow_partial: bool,
    ) -> QPoint:
        """Clamp a surface position using the drag or startup visibility bounds."""
        return self._geometry.clamp_to_screen(
            pos,
            screen=screen,
            width=width,
            height=height,
            allow_partial=allow_partial,
        )

    def commit_drag_position(
        self,
        cursor_local: QPoint | None,
        *,
        surface_screen: ScreenLike | None,
        screens: Sequence[ScreenLike],
        window_size: tuple[int, int],
    ) -> PositionCommit | None:
        """Persist an output-local placement after a successful drag."""
        if surface_screen is None:
            return None
        surface_geometry = surface_screen.geometry()
        surface_top_left = QPoint(
            surface_geometry.x() + self._layer_pos.x(),
            surface_geometry.y() + self._layer_pos.y(),
        )
        local = cursor_local if cursor_local is not None else self._drag.local
        cursor_global = QPoint(surface_top_left.x() + local.x(), surface_top_left.y() + local.y())
        target_screen = self.screen_for_global_point(cursor_global, screens, surface_screen)
        if target_screen is None:
            return None
        target_geometry = target_screen.geometry()
        width, height = window_size
        self.set_active_screen(target_screen)
        self._layer_pos = self.clamp_to_screen(
            QPoint(surface_top_left.x() - target_geometry.x(), surface_top_left.y() - target_geometry.y()),
            screen=target_screen,
            width=width,
            height=height,
            allow_partial=True,
        )
        if self._config.anchor_top:
            self._config.margin_edge = max(0, self._layer_pos.y())
        else:
            self._config.margin_edge = max(0, target_geometry.height() - height - self._layer_pos.y())
        self._config.margin_x = self._layer_pos.x() - (target_geometry.width() - width) // 2
        self._config.screen_name = target_screen.name()
        self._config.screen_width = target_geometry.width()
        self._config.screen_height = target_geometry.height()
        if not self.same_screen(surface_screen, target_screen):
            output = self.output(target_screen)
            if output is not None:
                moved = self._platform.move_to_output(output)
                if not moved.succeeded:
                    logger.warning("Output change failed: %s", moved.reason or "no reason given")
        elif self._platform.capabilities.layer_shell:
            self._platform.move_to(WindowPoint(self._layer_pos.x(), self._layer_pos.y()))
        return PositionCommit(self._config.margin_edge, self._config.margin_x, self._config.screen_name)

    def consume_preserve_position(self) -> bool:
        """Return and clear the one-shot position-preservation flag for showEvent."""
        preserve = self._preserve_layer_pos_on_show
        self._preserve_layer_pos_on_show = False
        return preserve


__all__ = [
    "OverlaySurfaceController",
    "PositionCommit",
    "ScreenLike",
]
