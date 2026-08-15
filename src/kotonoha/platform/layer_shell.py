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
