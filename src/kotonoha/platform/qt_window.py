"""Ordinary top-most window implementation of the overlay contract."""

from __future__ import annotations

from .overlay_contracts import (
    OverlayCapabilities,
    OverlayOperationResult,
    OverlayPlatform,
    WindowHost,
    WindowPoint,
    WindowPolicy,
    WindowRectangle,
)


class QtWindowPlatform(OverlayPlatform):
    """Use toolkit window flags when compositor-specific overlay APIs are absent."""

    def __init__(self, host: WindowHost, *, reason: str | None = None) -> None:
        self._host = host
        self._reason = reason
        self._capabilities = OverlayCapabilities(
            layer_shell=False,
            blur=False,
            input_region=True,
            output_rebinding=False,
            layer_shell_reason=reason,
            blur_reason="Ordinary windows cannot request compositor backdrop blur.",
            output_rebinding_reason="Ordinary windows cannot rebind a mapped output.",
        )

    @property
    def capabilities(self) -> OverlayCapabilities:
        return self._capabilities

    def prepare(self) -> OverlayOperationResult:
        try:
            self._host.apply_window_policy(WindowPolicy(recreate_surface=True))
        except RuntimeError as exc:
            return OverlayOperationResult.failure(f"Window initialization failed: {exc}")
        return OverlayOperationResult.success()

    def activate(self) -> OverlayOperationResult:
        return OverlayOperationResult.success()

    def set_input_region(self, region: WindowRectangle | None) -> OverlayOperationResult:
        try:
            self._host.apply_window_policy(
                WindowPolicy(
                    does_not_accept_focus=region is None,
                    show_without_activating=region is None,
                    mouse_events_transparent=region is None,
                    recreate_surface=False,
                )
            )
            self._host.refresh()
        except RuntimeError as exc:
            return OverlayOperationResult.failure(f"Input mode update failed: {exc}")
        return OverlayOperationResult.success()

    def set_blur_region(self, region: WindowRectangle | None, radius: int = 0) -> OverlayOperationResult:
        del region, radius
        return OverlayOperationResult.failure(self._capabilities.blur_reason or "Blur is unavailable.")

    def move_to(self, position: WindowPoint) -> OverlayOperationResult:
        try:
            self._host.move_window(position)
        except RuntimeError as exc:
            return OverlayOperationResult.failure(f"Window move failed: {exc}")
        return OverlayOperationResult.success()

    def rebind_output(self, output: WindowRectangle) -> OverlayOperationResult:
        del output
        return OverlayOperationResult.failure(
            self._capabilities.output_rebinding_reason or "Output rebinding is unavailable."
        )
