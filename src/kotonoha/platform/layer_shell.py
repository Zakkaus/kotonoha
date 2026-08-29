"""Layer-shell adapter over Kotonoha's existing native controller."""

from __future__ import annotations

import logging

from .overlay_contracts import (
    DragGeometry,
    DragMode,
    DragPort,
    DragStartResult,
    DragUpdateResult,
    LayerShellBridge,
    OverlayCapabilities,
    SurfaceResult,
    WindowHost,
    WindowPoint,
    WindowPolicy,
    WindowRectangle,
)

logger = logging.getLogger(__name__)


class _LayerShellDragStrategy:
    """Commit a dragged Layer Shell surface through the bridge's anchor.

    The two strategies below differ in one thing: which pointer reading they measure
    the displacement from, and whether that reading is re-anchored after each commit.
    Everything else — the window handle, the anchor call, its two failure modes and
    the committed position — was written out twice, so a fix to either copy had to be
    remembered for the other.
    """

    #: Whether the origin moves to the latest reading after each committed step.
    _reanchors = False
    #: Names this strategy in the "drag has not started" result.
    _label = "Layer Shell"

    def __init__(self, host: WindowHost, controller: LayerShellBridge) -> None:
        self._host = host
        self._controller = controller
        self._position = WindowPoint(0, 0)
        self._panel_position: WindowPoint | None = None
        self._origin: WindowPoint | None = None

    @property
    def client_positioning(self) -> bool:
        """Layer Shell can persist an output-local position through its anchor."""
        return True

    def _reading(self, local_position: WindowPoint, global_position: WindowPoint) -> WindowPoint:
        raise NotImplementedError

    def set_position(self, position: WindowPoint) -> None:
        self._position = position

    def begin_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
        geometry: DragGeometry,
    ) -> DragStartResult:
        self._position = geometry.surface_position
        self._panel_position = WindowPoint(
            geometry.surface_position.x + geometry.panel.x,
            geometry.surface_position.y + geometry.panel.y,
        )
        self._origin = self._reading(local_position, global_position)
        return DragStartResult(DragMode.MANUAL)

    def update_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
        geometry: DragGeometry,
    ) -> DragUpdateResult:
        origin = self._origin
        panel_position = self._panel_position
        if origin is None or panel_position is None:
            return DragUpdateResult(
                SurfaceResult.rejected(f"{self._label} drag has not started"),
                self._position,
            )
        reading = self._reading(local_position, global_position)
        attempted_panel = WindowPoint(
            panel_position.x + reading.x - origin.x,
            panel_position.y + reading.y - origin.y,
        )
        position = geometry.surface_for_panel(attempted_panel)
        pointer = self._host.native_window_pointer()
        if pointer is None:
            return DragUpdateResult(
                SurfaceResult.failed("Layer Shell window handle is unavailable", retryable=True),
                self._position,
            )
        if position != self._position:
            try:
                self._controller.set_anchor_position(pointer, position.x, position.y)
            except (OSError, RuntimeError):
                return DragUpdateResult(
                    SurfaceResult.failed("Layer Shell position update failed", retryable=True),
                    self._position,
                )
        self._position = position
        self._panel_position = attempted_panel
        if self._reanchors:
            self._origin = reading
        return DragUpdateResult(SurfaceResult.applied(), position)

    def end_drag(self) -> None:
        self._origin = None
        self._panel_position = None


class LayerShellAnchorDragStrategy(_LayerShellDragStrategy):
    """Move a Layer Shell surface with press-relative local pointer deltas."""

    # The anchor stays where the press landed. The surface follows the pointer, so
    # the pointer's local position re-settles toward that anchor by itself;
    # re-anchoring here counts that settling twice and the panel accelerates away,
    # which is the runaway drag #7 and #9 were about.
    _reanchors = False

    def _reading(self, local_position: WindowPoint, global_position: WindowPoint) -> WindowPoint:
        del global_position
        return local_position


class NiriLayerShellDragStrategy(_LayerShellDragStrategy):
    """Move a Layer Shell surface using global pointer deltas."""

    # niri configures asynchronously, so the surface has not moved under the pointer
    # by the next event and the local reading does not re-settle. The global reading
    # is re-anchored each step to keep the displacement incremental.
    _reanchors = True
    _label = "Niri Layer Shell"

    def _reading(self, local_position: WindowPoint, global_position: WindowPoint) -> WindowPoint:
        del local_position
        return global_position


class LayerShellPlatform:
    """Adapt Layer Shell surface, input, blur, placement and drag operations."""

    def __init__(
        self,
        host: WindowHost,
        controller: LayerShellBridge,
        drag_strategy: DragPort | None = None,
    ) -> None:
        self._host = host
        self._controller = controller
        self._drag_strategy = (
            drag_strategy if drag_strategy is not None else LayerShellAnchorDragStrategy(host, controller)
        )
        self._surface_released = False
        self._closed = False

    @property
    def capabilities(self) -> OverlayCapabilities:
        """Read live, not snapshotted at construction.

        blur_available is a live probe by contract: ext-background-effect-v1 sends
        its capabilities event again whenever the answer changes. A snapshot kept
        reporting blur after the compositor withdrew it, and kept reporting none
        after it gained it, until the adapter was rebuilt."""
        # A layer surface only exists on Wayland, which has no window-opacity protocol.
        return OverlayCapabilities.from_controller(self._controller, window_opacity=False)

    @property
    def client_positioning(self) -> bool:
        """Expose the drag-relevant placement capability through the drag port."""
        return self.capabilities.client_positioning

    def _pointer(self) -> int | None:
        return self._host.native_window_pointer()

    def prepare(self) -> SurfaceResult:
        if self._closed:
            return SurfaceResult.rejected("The Layer Shell adapter is closed.")
        try:
            self._host.apply_window_policy(WindowPolicy(recreate_surface=True))
        except RuntimeError as exc:
            return SurfaceResult.failed(f"Layer Shell window initialization failed: {exc}", retryable=True)
        return SurfaceResult.applied()

    def activate(self) -> SurfaceResult:
        if self._closed:
            return SurfaceResult.rejected("The Layer Shell adapter is closed.")
        pointer = self._pointer()
        if pointer is None:
            return SurfaceResult.failed("Layer Shell window handle is unavailable.", retryable=True)
        if not self._controller.available:
            return SurfaceResult.not_supported(
                self._controller.disabled_reason or "Layer Shell is unavailable."
            )
        try:
            self._controller.make_overlay(pointer)
        except (OSError, RuntimeError):
            return SurfaceResult.failed("Layer Shell activation failed.", retryable=True)
        self._surface_released = False
        return SurfaceResult.applied()

    def set_input_region(self, region: WindowRectangle | None) -> SurfaceResult:
        if self._closed:
            return SurfaceResult.rejected("The Layer Shell adapter is closed.")
        capabilities = self.capabilities
        if not capabilities.input_region:
            # The bridge no-ops silently when Layer Shell is unavailable, so
            # returning success here told the caller an update happened that did not.
            return SurfaceResult.not_supported(
                capabilities.input_region_reason or "Layer Shell input regions are unavailable."
            )
        pointer = self._pointer()
        if pointer is None:
            return SurfaceResult.failed("Layer Shell window handle is unavailable.", retryable=True)
        try:
            if region is None:
                self._controller.set_passthrough(pointer, True)
            else:
                self._controller.set_input_rect(pointer, region.x, region.y, region.width, region.height)
        except (OSError, RuntimeError):
            return SurfaceResult.failed("Layer Shell input region update failed.", retryable=True)
        return SurfaceResult.applied()

    def set_blur_region(self, region: WindowRectangle | None, radius: int = 0) -> SurfaceResult:
        if self._closed:
            return SurfaceResult.rejected("The Layer Shell adapter is closed.")
        capabilities = self.capabilities
        if not capabilities.blur:
            return SurfaceResult.not_supported(capabilities.blur_reason or "Blur is unavailable.")
        pointer = self._pointer()
        if pointer is None:
            return SurfaceResult.failed("Layer Shell window handle is unavailable.", retryable=True)
        try:
            if region is None:
                self._controller.clear_blur(pointer)
            else:
                self._controller.set_blur_region(pointer, region.x, region.y, region.width, region.height, radius)
        except (OSError, RuntimeError):
            return SurfaceResult.failed("Layer Shell blur update failed.", retryable=True)
        return SurfaceResult.applied()

    def move_to(self, position: WindowPoint) -> SurfaceResult:
        if self._closed:
            return SurfaceResult.rejected("The Layer Shell adapter is closed.")
        capabilities = self.capabilities
        if not capabilities.layer_shell:
            return SurfaceResult.not_supported(
                capabilities.layer_shell_reason or "Layer Shell is unavailable."
            )
        pointer = self._pointer()
        if pointer is None:
            return SurfaceResult.failed("Layer Shell window handle is unavailable.", retryable=True)
        try:
            self._controller.set_anchor_position(pointer, position.x, position.y)
        except (OSError, RuntimeError):
            return SurfaceResult.failed("Layer Shell position update failed", retryable=True)
        self._drag_strategy.set_position(position)
        return SurfaceResult.applied()

    def release_for_output_rebind(self) -> SurfaceResult:
        """Release resources keyed by the old surface before recreation."""
        return self.release_surface()

    def release_surface(self) -> SurfaceResult:
        """Hide and destroy the surface after releasing compositor resources."""
        if self._surface_released:
            return SurfaceResult.applied()
        if not self._host.is_alive():
            self._surface_released = True
            return SurfaceResult.applied()

        failures: list[str] = []
        for result in (self._release_input(), self._release_blur()):
            if not result.succeeded and result.reason is not None:
                failures.append(result.reason)
        try:
            self._host.hide_window()
            self._host.destroy_surface()
        except RuntimeError as exc:
            failures.append(f"Layer Shell surface release failed: {exc}")
        self._surface_released = not failures
        if failures:
            return SurfaceResult.failed("; ".join(failures), retryable=True)
        return SurfaceResult.applied()

    def close(self) -> SurfaceResult:
        """Release the surface and prevent any later platform operation."""
        if self._closed:
            return SurfaceResult.applied()
        result = self.release_surface()
        self._drag_strategy.end_drag()
        if result.succeeded:
            self._closed = True
        return result

    def _release_input(self) -> SurfaceResult:
        """Make the old Layer Shell surface click-through before destruction."""
        pointer = self._pointer()
        if pointer is None:
            return SurfaceResult.applied()
        try:
            self._controller.set_passthrough(pointer, True)
        except (OSError, RuntimeError) as exc:
            return SurfaceResult.failed(f"Layer Shell input release failed: {exc}", retryable=True)
        return SurfaceResult.applied()

    def _release_blur(self) -> SurfaceResult:
        """Drop the compositor-side blur object before its surface goes.

        The bridge keys the effect on the wl_surface, and a rebuilt surface gets a
        new address, so one left behind can never be found again — it would leak
        for the life of the process, once per output change.

        No capability is consulted. The effect was created while blur was
        advertised, and a compositor that has since withdrawn it does not un-create
        it; the construction-time snapshot skipped the release when blur arrived
        after startup, and the live answer would skip it in exactly the withdrawn
        case where the object still exists. clear_blur is a no-op when the bridge
        has no such symbol, so an unconditional release costs nothing.
        """
        pointer = self._pointer()
        if pointer is None:
            return SurfaceResult.applied()
        try:
            self._controller.clear_blur(pointer)
        except (OSError, RuntimeError) as exc:
            logger.warning("Blur release failed before the surface was destroyed: %s", exc)
            return SurfaceResult.failed(f"Blur release failed: {exc}", retryable=True)
        return SurfaceResult.applied()

    def begin_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
        geometry: DragGeometry,
    ) -> DragStartResult:
        if self._closed:
            return DragStartResult(DragMode.UNAVAILABLE, "The Layer Shell adapter is closed.")
        return self._drag_strategy.begin_drag(local_position, global_position, geometry)

    def update_drag(
        self,
        local_position: WindowPoint,
        global_position: WindowPoint,
        geometry: DragGeometry,
    ) -> DragUpdateResult:
        if self._closed:
            return DragUpdateResult(
                SurfaceResult.rejected("The Layer Shell adapter is closed."),
                geometry.surface_position,
            )
        return self._drag_strategy.update_drag(local_position, global_position, geometry)

    def end_drag(self) -> None:
        self._drag_strategy.end_drag()

    def set_position(self, position: WindowPoint) -> None:
        """Synchronize the drag strategy after a committed anchor move."""
        self._drag_strategy.set_position(position)
