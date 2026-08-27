"""Stateful manual-drag adapter for an overlay platform."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QPoint

from ..platform.overlay_contracts import DragMode, DragPort, SurfaceResult, WindowPoint


@dataclass(frozen=True)
class DragRelease:
    """Outcome of a completed manual drag."""

    moved: bool
    should_commit: bool


class OverlayDragController:
    """Own pointer-gesture state while the surface owns its screen position."""

    def __init__(self, platform: DragPort) -> None:
        """Create a drag controller bound to one platform adapter."""
        self._platform = platform
        self._dragging = False
        self._drag_moved = False
        self._drag_applied = True
        self._drag_local = QPoint()

    @property
    def platform(self) -> DragPort:
        """Return the platform used for the active gesture."""
        return self._platform

    @platform.setter
    def platform(self, value: DragPort) -> None:
        self._platform = value

    @property
    def dragging(self) -> bool:
        """Whether a manual drag gesture is active."""
        return self._dragging

    @dragging.setter
    def dragging(self, value: bool) -> None:
        self._dragging = value

    @property
    def moved(self) -> bool:
        """Whether the active gesture changed the requested position."""
        return self._drag_moved

    @moved.setter
    def moved(self, value: bool) -> None:
        self._drag_moved = value

    @property
    def applied(self) -> bool:
        """Whether platform accepted every movement in the gesture."""
        return self._drag_applied

    @applied.setter
    def applied(self, value: bool) -> None:
        self._drag_applied = value

    @property
    def local(self) -> QPoint:
        """Return the last pointer coordinate in widget space."""
        return self._drag_local

    @local.setter
    def local(self, value: QPoint) -> None:
        self._drag_local = value

    def begin(self, local: QPoint, global_position: QPoint) -> DragMode:
        """Ask the platform for a manual drag and initialize gesture state."""
        result = self._platform.begin_drag(
            WindowPoint(local.x(), local.y()),
            WindowPoint(global_position.x(), global_position.y()),
        )
        if result.mode is not DragMode.MANUAL:
            return result.mode
        self._dragging = True
        self._drag_moved = False
        self._drag_applied = True
        self._drag_local = local
        return result.mode

    def update(
        self,
        position: QPoint,
        local: QPoint,
        global_position: QPoint,
    ) -> tuple[QPoint, SurfaceResult]:
        """Apply one local delta and return the platform result plus new position."""
        diff = local - self._drag_local
        if not diff.isNull():
            self._drag_moved = True
        updated_position = position + diff
        result = self._platform.update_drag(
            WindowPoint(local.x(), local.y()),
            WindowPoint(global_position.x(), global_position.y()),
        )
        if not result.succeeded:
            self._drag_applied = False
        return updated_position, result

    def end(self) -> DragRelease:
        """End the gesture and report whether persistence is safe."""
        moved = self._drag_moved
        should_commit = moved and self._drag_applied and self._platform.client_positioning
        self._dragging = False
        self._drag_moved = False
        self._drag_applied = True
        self._platform.end_drag()
        return DragRelease(moved, should_commit)


__all__ = ["DragRelease", "OverlayDragController"]
