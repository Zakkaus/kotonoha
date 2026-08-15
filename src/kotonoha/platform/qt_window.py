"""Ordinary top-most window implementation of the overlay contract."""

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


class QtWindowPlatform(OverlayPlatform):
    """Use toolkit window flags when compositor-specific overlay APIs are absent."""

    def __init__(
        self, host: WindowHost, *, reason: str | None = None, blur: LayerShellBridge | None = None
    ) -> None:
        self._host = host
        self._reason = reason
        # Blur is a separate capability from Layer Shell: Mutter offers no
        # layer-shell and does speak ext-background-effect-v1, so hardcoding
        # blur=False here dropped the frosted panel on exactly the compositor the
        # blur work was for. When a bridge is available the answer comes from it.
        self._blur = blur

    @property
    def capabilities(self) -> OverlayCapabilities:
        blur = self._blur is not None and self._blur.blur_available
        return OverlayCapabilities(
            layer_shell=False,
            blur=blur,
            input_region=True,
            output_rebinding=False,
            layer_shell_reason=self._reason,
            blur_reason=None
            if blur
            else (
                getattr(self._blur, "blur_disabled_reason", "protocol")
                if self._blur is not None
                else "Ordinary windows have no bridge to request compositor blur."
            ),
            output_rebinding_reason="Ordinary windows cannot rebind a mapped output.",
        )

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
            # The rectangle was ignored before: only the whole-window pass-through
            # switch was applied, so an unlocked ordinary window kept accepting
            # clicks across its entire transparent area and swallowed input meant
            # for whatever sits behind it. Click-through is carried by the policy
            # flag above, so the mask is cleared rather than set to nothing —
            # a shaping that fought the flag would be ambiguous.
            if region is None:
                self._host.clear_input_mask()
            else:
                self._host.set_input_mask(region)
            self._host.refresh()
        except RuntimeError as exc:
            return OverlayOperationResult.failure(f"Input mode update failed: {exc}")
        return OverlayOperationResult.success()

    def set_blur_region(self, region: WindowRectangle | None, radius: int = 0) -> OverlayOperationResult:
        # An ordinary window can still carry a compositor blur where the protocol
        # exists — Mutter has no Layer Shell and does speak it — so this is a real
        # operation here, not a permanent failure.
        capabilities = self.capabilities
        if not capabilities.blur or self._blur is None:
            return OverlayOperationResult.failure(capabilities.blur_reason or "Blur is unavailable.")
        pointer = self._host.native_window_pointer()
        if pointer is None:
            return OverlayOperationResult.failure("The window handle is unavailable.")
        try:
            if region is None:
                self._blur.clear_blur(pointer)
            else:
                self._blur.set_blur_region(pointer, region.x, region.y, region.width, region.height, radius)
        except (OSError, RuntimeError):
            return OverlayOperationResult.failure("Blur update failed.")
        return OverlayOperationResult.success()

    def move_to(self, position: WindowPoint) -> OverlayOperationResult:
        try:
            self._host.move_window(position)
        except RuntimeError as exc:
            return OverlayOperationResult.failure(f"Window move failed: {exc}")
        # Reporting success because move_window() did not raise is not evidence the
        # window moved: a Wayland compositor without Layer Shell ignores a
        # client-side move of a toplevel, and the caller then persisted a position
        # the visible window never took. Ask where the window actually is.
        landed = self._host.window_position()
        if landed is not None and landed != position:
            return OverlayOperationResult.failure(
                "The compositor did not apply the move; this window cannot be positioned by the client."
            )
        return OverlayOperationResult.success()

    def rebind_output(self, output: WindowRectangle) -> OverlayOperationResult:
        del output
        return OverlayOperationResult.failure(
            self.capabilities.output_rebinding_reason or "Output rebinding is unavailable."
        )
