"""Own overlay placement state and cross-output position commits."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PyQt6.QtCore import QPoint

from ..config import Config
from ..platform.overlay_contracts import (
    DragMode,
    Output,
    OverlayPlatform,
    SurfaceResult,
    WindowPoint,
)
from ..platform.surface_lifecycle import SurfaceLifecycleOwner
from .drag import DragRelease, OverlayDragController
from .geometry import OverlayGeometry, ScreenLike

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PositionCommit:
    """Output-local placement persisted after a successful platform operation."""

    margin_edge: int
    margin_x: int
    screen_name: str


@dataclass(frozen=True, slots=True)
class _PendingPlacement:
    """Placement that must be committed after a cross-output rebuild succeeds."""

    screen: ScreenLike
    layer_pos: QPoint
    commit: PositionCommit


class OverlayPositionController:
    """Coordinate drag state, output selection, and placement persistence."""

    def __init__(
        self,
        config: Config,
        geometry: OverlayGeometry,
        platform: OverlayPlatform,
        lifecycle: SurfaceLifecycleOwner,
    ) -> None:
        """Create a placement owner around the shared platform lifecycle."""
        self._config = config
        self._geometry = geometry
        self._platform = platform
        self._lifecycle = lifecycle
        self._drag = OverlayDragController(platform.drag)
        self._layer_pos = QPoint()
        self._active_screen: ScreenLike | None = None
        self._selected_screen: ScreenLike | None = None
        self._pending_placement: _PendingPlacement | None = None
        self._pending_rebuild_screen: ScreenLike | None = None
        self._preserve_layer_pos_on_show = False
        self._rebind_in_progress = False
        self._completed_position_commit: PositionCommit | None = None
        self._position_commit_handler: Callable[[PositionCommit], None] | None = None

    @property
    def layer_pos(self) -> QPoint:
        """Return the current output-local surface position."""
        return self._layer_pos

    @layer_pos.setter
    def layer_pos(self, value: QPoint) -> None:
        self._layer_pos = value

    @property
    def active_screen(self) -> ScreenLike | None:
        """Return the output whose position was committed."""
        return self._active_screen

    @active_screen.setter
    def active_screen(self, value: ScreenLike | None) -> None:
        # Kept as a narrow test/compatibility seam. Production code commits this
        # value through _commit_position or a successful surface activation.
        self._active_screen = value

    @property
    def selected_screen(self) -> ScreenLike | None:
        """Return the output selected for geometry before platform commit."""
        return self._selected_screen

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
        """Use the current placement settings for subsequent calculations."""
        self._config = config

    def select_screen(self, screen: ScreenLike | None) -> None:
        """Select an output for geometry without claiming its platform binding."""
        self._selected_screen = screen

    def set_position_commit_handler(self, handler: Callable[[PositionCommit], None]) -> None:
        """Register the callback for an asynchronously completed placement."""
        self._position_commit_handler = handler

    def begin_drag(self, local: QPoint, global_position: QPoint) -> DragMode:
        """Start a manual drag through the selected drag port."""
        return self._drag.begin(local, global_position)

    def update_drag(self, local: QPoint, global_position: QPoint) -> SurfaceResult:
        """Apply one incremental drag delta and retain the platform result."""
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
        """Clamp a surface position using the configured visibility bounds."""
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
        """Persist output-local placement only after its platform operation succeeds."""
        if surface_screen is None:
            return None
        surface_geometry = surface_screen.geometry()
        surface_top_left = QPoint(
            surface_geometry.x() + self._layer_pos.x(),
            surface_geometry.y() + self._layer_pos.y(),
        )
        local = cursor_local if cursor_local is not None else self._drag.local
        cursor_global = QPoint(surface_top_left.x() + local.x(), surface_top_left.y() + local.y())
        target_screen = OverlayGeometry.screen_for_global_point(cursor_global, screens, surface_screen)
        if target_screen is None:
            return None
        target_geometry = target_screen.geometry()
        width, height = window_size
        target_pos = self.clamp_to_screen(
            QPoint(surface_top_left.x() - target_geometry.x(), surface_top_left.y() - target_geometry.y()),
            screen=target_screen,
            width=width,
            height=height,
            allow_partial=True,
        )
        commit = self._position_commit(target_screen, target_pos, width, height)

        if not OverlayGeometry.same_screen(surface_screen, target_screen) and self._platform.output_binding is not None:
            output = OverlayGeometry.output(target_screen)
            if output is None:
                return None
            self._pending_placement = _PendingPlacement(target_screen, target_pos, commit)
            self._completed_position_commit = None
            self._rebind_in_progress = True
            try:
                result = self._lifecycle.rebind(output)
            finally:
                self._rebind_in_progress = False
            if not result.succeeded:
                self._log_result("output change", result)
                return None
            completed = self._completed_position_commit
            self._completed_position_commit = None
            return completed

        if self._platform.capabilities.layer_shell:
            placement = self._platform.placement
            if placement is None:
                self._log_result("drag placement", SurfaceResult.not_supported("Placement is unavailable."))
                return None
            result = placement.move_to(WindowPoint(target_pos.x(), target_pos.y()))
            if not result.succeeded:
                self._log_result("drag placement", result)
                return None
        self._commit_position(target_screen, target_pos, commit)
        return commit

    def begin_rebuild(self, screen: ScreenLike) -> QPoint:
        """Record a rebuild target and choose its output-local position."""
        self._pending_rebuild_screen = screen
        pending = self._pending_placement
        if pending is not None and pending.screen.name() == screen.name():
            position = pending.layer_pos
            reset_position = False
        else:
            position = self._geometry.compute_layer_pos(*self._geometry.window_size(screen), screen)
            reset_position = True
        self._selected_screen = screen
        self._layer_pos = position
        self._preserve_layer_pos_on_show = not reset_position
        return position

    def rebuild_failed(self) -> None:
        """Clear only the in-flight rebuild marker and retain pending intent."""
        self._pending_rebuild_screen = None

    def complete_rebind(self, output: Output) -> None:
        """Commit logical output and pending placement after a rebuilt surface is active."""
        screen = self._pending_rebuild_screen
        pending = self._pending_placement
        if pending is not None and pending.screen.name() == output.name:
            self._commit_position(pending.screen, pending.layer_pos, pending.commit)
            self._pending_placement = None
            if self._rebind_in_progress:
                self._completed_position_commit = pending.commit
            elif self._position_commit_handler is not None:
                self._position_commit_handler(pending.commit)
            screen = pending.screen
        if screen is not None and screen.name() == output.name:
            self._selected_screen = screen
            self._active_screen = screen
        self._pending_rebuild_screen = None

    def consume_preserve_position(self) -> bool:
        """Return and clear the one-shot position-preservation flag for showEvent."""
        preserve = self._preserve_layer_pos_on_show
        self._preserve_layer_pos_on_show = False
        return preserve

    def _position_commit(self, screen: ScreenLike, position: QPoint, width: int, height: int) -> PositionCommit:
        """Calculate a persistence DTO without mutating Config."""
        geometry = screen.geometry()
        margin_edge = (
            max(0, position.y())
            if self._config.anchor_top
            else max(0, geometry.height() - height - position.y())
        )
        margin_x = position.x() - (geometry.width() - width) // 2
        return PositionCommit(margin_edge, margin_x, screen.name())

    def _commit_position(self, screen: ScreenLike, position: QPoint, commit: PositionCommit) -> None:
        """Apply a placement DTO after the platform has accepted it."""
        geometry = screen.geometry()
        self._layer_pos = position
        self._selected_screen = screen
        self._active_screen = screen
        self._config.margin_edge = commit.margin_edge
        self._config.margin_x = commit.margin_x
        self._config.screen_name = commit.screen_name
        self._config.screen_width = geometry.width()
        self._config.screen_height = geometry.height()

    @staticmethod
    def _log_result(name: str, result: SurfaceResult) -> None:
        """Make ignored platform failures observable without changing UI policy."""
        if result.succeeded:
            return
        logger.warning("%s was not applied: %s", name, result.reason or "unknown reason")


__all__ = ["OverlayPositionController", "PositionCommit"]
