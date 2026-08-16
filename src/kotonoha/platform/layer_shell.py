"""Layer-shell adapter over Kotonoha's existing native controller."""

from __future__ import annotations

from .overlay_contracts import (
    DragMode,
    DragStartResult,
    LayerShellBridge,
    OverlayCapabilities,
    OverlayDragStrategy,
    OverlayOperationResult,
    WindowHost,
    WindowPoint,
    WindowPolicy,
    WindowRectangle,
)


class LayerShellAnchorDragStrategy:
    """Move a Layer Shell surface with press-relative local pointer deltas."""

    def __init__(self, host: WindowHost, controller: LayerShellBridge) -> None:
        self._host = host
        self._controller = controller
        self._position = WindowPoint(0, 0)
        self._drag_local: WindowPoint | None = None

    def set_position(self, position: WindowPoint) -> None:
        self._position = position

    def begin_drag(self, local_position: WindowPoint, global_position: WindowPoint) -> DragStartResult:
        del global_position
        self._drag_local = local_position
        return DragStartResult(DragMode.MANUAL)

    def update_drag(self, local_position: WindowPoint, global_position: WindowPoint) -> OverlayOperationResult:
        del global_position
        if self._drag_local is None:
            return OverlayOperationResult.failure("Layer Shell drag has not started")
        delta = local_position.x - self._drag_local.x, local_position.y - self._drag_local.y
        position = WindowPoint(self._position.x + delta[0], self._position.y + delta[1])
        pointer = self._host.native_window_pointer()
        if pointer is None:
            return OverlayOperationResult.failure("Layer Shell window handle is unavailable")
        try:
            self._controller.set_anchor_position(pointer, position.x, position.y)
        except (OSError, RuntimeError):
            return OverlayOperationResult.failure("Layer Shell position update failed")
        self._position = position
        # The anchor stays where the press landed. The surface follows the pointer,
        # so the pointer's local position re-settles toward that anchor by itself;
        # advancing it here counts that settling twice and the panel accelerates
        # away, which is the runaway drag #7 and #9 were about.
        return OverlayOperationResult.success()

    def end_drag(self) -> None:
        self._drag_local = None


class LayerShellPlatform:
    """Drive layer-shell, input, blur, positioning, and output binding calls."""

    def __init__(
        self,
        host: WindowHost,
        controller: LayerShellBridge,
        drag_strategy: OverlayDragStrategy | None = None,
    ) -> None:
        self._host = host
        self._controller = controller
        self._drag_strategy = drag_strategy or LayerShellAnchorDragStrategy(host, controller)
        self._capabilities = OverlayCapabilities(
            layer_shell=controller.available,
            blur=controller.blur_available,
            input_region=controller.available,
            output_rebinding=controller.available,
            layer_shell_reason=controller.disabled_reason,
            blur_reason=None if controller.blur_available else "Compositor does not advertise a blur protocol.",
            input_region_reason=None if controller.available else "Layer Shell input regions are unavailable.",
            output_rebinding_reason=None if controller.available else "Layer Shell output rebinding is unavailable.",
        )

    @property
    def capabilities(self) -> OverlayCapabilities:
        """Read live, not snapshotted at construction.

        blur_available is a live probe by contract: ext-background-effect-v1 sends
        its capabilities event again whenever the answer changes. A snapshot kept
        reporting blur after the compositor withdrew it, and kept reporting none
        after it gained it, until the adapter was rebuilt."""
        return OverlayCapabilities.from_controller(self._controller)

    def _pointer(self) -> int | None:
        return self._host.native_window_pointer()

    def prepare(self) -> OverlayOperationResult:
        try:
            self._host.apply_window_policy(WindowPolicy(recreate_surface=True))
        except RuntimeError as exc:
            return OverlayOperationResult.failure(f"Layer Shell window initialization failed: {exc}")
        return OverlayOperationResult.success()

    def activate(self) -> OverlayOperationResult:
        pointer = self._pointer()
        if pointer is None:
            return OverlayOperationResult.failure("Layer Shell window handle is unavailable.")
        if not self._controller.available:
            return OverlayOperationResult.failure(
                self._controller.disabled_reason or "Layer Shell is unavailable."
            )
        try:
            self._controller.make_overlay(pointer)
        except (OSError, RuntimeError):
            return OverlayOperationResult.failure("Layer Shell activation failed.")
        return OverlayOperationResult.success()

    def set_input_region(self, region: WindowRectangle | None) -> OverlayOperationResult:
        capabilities = self.capabilities
        if not capabilities.input_region:
            # The bridge no-ops silently when Layer Shell is unavailable, so
            # returning success here told the caller an update happened that did not.
            return OverlayOperationResult.failure(
                capabilities.input_region_reason or "Layer Shell input regions are unavailable."
            )
        pointer = self._pointer()
        if pointer is None:
            return OverlayOperationResult.failure("Layer Shell window handle is unavailable.")
        try:
            if region is None:
                self._controller.set_passthrough(pointer, True)
            else:
                self._controller.set_input_rect(pointer, region.x, region.y, region.width, region.height)
        except (OSError, RuntimeError):
            return OverlayOperationResult.failure("Layer Shell input region update failed.")
        return OverlayOperationResult.success()

    def set_blur_region(self, region: WindowRectangle | None, radius: int = 0) -> OverlayOperationResult:
        capabilities = self.capabilities
        if not capabilities.blur:
            return OverlayOperationResult.failure(capabilities.blur_reason or "Blur is unavailable.")
        pointer = self._pointer()
        if pointer is None:
            return OverlayOperationResult.failure("Layer Shell window handle is unavailable.")
        try:
            if region is None:
                self._controller.clear_blur(pointer)
            else:
                self._controller.set_blur_region(pointer, region.x, region.y, region.width, region.height, radius)
        except (OSError, RuntimeError):
            return OverlayOperationResult.failure("Layer Shell blur update failed.")
        return OverlayOperationResult.success()

    def move_to(self, position: WindowPoint) -> OverlayOperationResult:
        capabilities = self.capabilities
        if not capabilities.layer_shell:
            return OverlayOperationResult.failure(
                capabilities.layer_shell_reason or "Layer Shell is unavailable."
            )
        pointer = self._pointer()
        if pointer is None:
            return OverlayOperationResult.failure("Layer Shell window handle is unavailable.")
        try:
            self._controller.set_anchor_position(pointer, position.x, position.y)
        except (OSError, RuntimeError):
            return OverlayOperationResult.failure("Layer Shell position update failed.")
        self._drag_strategy.set_position(position)
        return OverlayOperationResult.success()

    def rebind_output(self, output: WindowRectangle) -> OverlayOperationResult:
        capabilities = self.capabilities
        if not capabilities.output_rebinding:
            # host.bind_output not raising is not evidence the output was rebound:
            # without Layer Shell there is no surface to bind.
            return OverlayOperationResult.failure(
                capabilities.output_rebinding_reason or "Output rebinding is unavailable."
            )
        try:
            self._host.bind_output(output)
        except RuntimeError as exc:
            return OverlayOperationResult.failure(f"Output rebinding failed: {exc}")
        return OverlayOperationResult.success()

    def begin_drag(self, local_position: WindowPoint, global_position: WindowPoint) -> DragStartResult:
        return self._drag_strategy.begin_drag(local_position, global_position)

    def update_drag(self, local_position: WindowPoint, global_position: WindowPoint) -> OverlayOperationResult:
        return self._drag_strategy.update_drag(local_position, global_position)

    def end_drag(self) -> None:
        self._drag_strategy.end_drag()
