"""Layer-shell adapter over Kotonoha's existing native controller."""

from __future__ import annotations

from .overlay_contracts import (
    LayerShellBridge,
    OverlayCapabilities,
    OverlayOperationResult,
    OverlayPlatform,
    WindowHost,
    WindowPoint,
    WindowPolicy,
    WindowRectangle,
)


class LayerShellPlatform(OverlayPlatform):
    """Drive layer-shell, input, blur, positioning, and output binding calls."""

    def __init__(self, host: WindowHost, controller: LayerShellBridge) -> None:
        self._host = host
        self._controller = controller
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
        return self._capabilities

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
        if not self._capabilities.blur:
            return OverlayOperationResult.failure(self._capabilities.blur_reason or "Blur is unavailable.")
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
        pointer = self._pointer()
        if pointer is None:
            return OverlayOperationResult.failure("Layer Shell window handle is unavailable.")
        try:
            self._controller.set_anchor_position(pointer, position.x, position.y)
        except (OSError, RuntimeError):
            return OverlayOperationResult.failure("Layer Shell position update failed.")
        return OverlayOperationResult.success()

    def rebind_output(self, output: WindowRectangle) -> OverlayOperationResult:
        try:
            self._host.bind_output(output)
        except RuntimeError as exc:
            return OverlayOperationResult.failure(f"Output rebinding failed: {exc}")
        return OverlayOperationResult.success()
