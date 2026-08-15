"""Layer-shell adapter over Kotonoha's existing native controller."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PyQt6.QtCore import QTimer

from .overlay_contracts import (
    DragMode,
    DragStartResult,
    LayerShellBridge,
    Output,
    OverlayCapabilities,
    OverlayDragStrategy,
    OverlayOperationResult,
    WindowHost,
    WindowPoint,
    WindowPolicy,
    WindowRectangle,
)

logger = logging.getLogger(__name__)

RESURFACE_DELAY_MS = 250


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


class NiriLayerShellDragStrategy:
    """Move a Layer Shell surface using global pointer deltas."""

    def __init__(self, host: WindowHost, controller: LayerShellBridge) -> None:
        self._host = host
        self._controller = controller
        self._position = WindowPoint(0, 0)
        self._drag_global: WindowPoint | None = None

    def set_position(self, position: WindowPoint) -> None:
        self._position = position

    def begin_drag(self, local_position: WindowPoint, global_position: WindowPoint) -> DragStartResult:
        del local_position
        self._drag_global = global_position
        return DragStartResult(DragMode.MANUAL)

    def update_drag(self, local_position: WindowPoint, global_position: WindowPoint) -> OverlayOperationResult:
        del local_position
        if self._drag_global is None:
            return OverlayOperationResult.failure("Niri Layer Shell drag has not started")
        delta_x = global_position.x - self._drag_global.x
        delta_y = global_position.y - self._drag_global.y
        position = WindowPoint(self._position.x + delta_x, self._position.y + delta_y)
        pointer = self._host.native_window_pointer()
        if pointer is None:
            return OverlayOperationResult.failure("Layer Shell window handle is unavailable")
        try:
            self._controller.set_anchor_position(pointer, position.x, position.y)
        except (OSError, RuntimeError):
            return OverlayOperationResult.failure("Layer Shell position update failed")
        self._position = position
        self._drag_global = global_position
        return OverlayOperationResult.success()

    def end_drag(self) -> None:
        self._drag_global = None


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
        self._active_output: Output | None = None
        self._output_handler: Callable[[Output], bool] | None = None
        self._pending_resurface = False
        self._resurface_output: Output | None = None
        self._resurface_timer = QTimer()
        self._resurface_timer.setSingleShot(True)
        self._resurface_timer.setInterval(RESURFACE_DELAY_MS)
        self._resurface_timer.timeout.connect(self._restore_pending_surface)

    @property
    def capabilities(self) -> OverlayCapabilities:
        """Read live, not snapshotted at construction.

        blur_available is a live probe by contract: ext-background-effect-v1 sends
        its capabilities event again whenever the answer changes. A snapshot kept
        reporting blur after the compositor withdrew it, and kept reporting none
        after it gained it, until the adapter was rebuilt."""
        # A layer surface only exists on Wayland, which has no window-opacity protocol.
        return OverlayCapabilities.from_controller(self._controller, window_opacity=False)

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

    def set_output_handler(self, handler: Callable[[Output], bool]) -> None:
        self._output_handler = handler

    def set_active_output(self, output: Output | None) -> None:
        self._active_output = output

    def _release_blur(self) -> None:
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
            return
        try:
            self._controller.clear_blur(pointer)
        except (OSError, RuntimeError) as exc:
            logger.warning("Blur release failed before the surface was destroyed: %s", exc)

    def move_to_output(self, output: Output) -> OverlayOperationResult:
        """Put the overlay on another output.

        A layer surface binds its output when it is created and cannot be moved,
        so this destroys the surface and has the host build a new one there.
        Recording the output alone leaves the panel drawn on the output it was
        dragged away from."""
        self._active_output = output
        self._pending_resurface = False
        self._resurface_timer.stop()
        if not self._host.is_alive():
            return OverlayOperationResult.failure("The overlay window is gone.")
        self._host.hide_window()
        self._release_blur()
        self._host.destroy_surface()
        if self._output_handler is None:
            self._pending_resurface = True
            return OverlayOperationResult.failure("No output handler is registered.")
        if not self._output_handler(output):
            # The old surface is already destroyed. Clearing the debt up front and
            # then failing here left nothing owed and the active output already set
            # to the target, so the next output event returned early and the overlay
            # stayed hidden for the rest of the session. Stay owed instead.
            self._pending_resurface = True
            return OverlayOperationResult.failure("The surface was not rebuilt on the new output.")
        return OverlayOperationResult.success()

    def output_removed(self, output: Output, connected: tuple[Output, ...], configured_name: str | None) -> None:
        if self._resurface_output is not None and self._resurface_output.name == output.name:
            # It went away before the rebuild ran; drop the target but stay owed.
            self._resurface_timer.stop()
            self._resurface_output = None
            self._pending_resurface = True
        if self._active_output is None or self._active_output.name != output.name:
            return
        self._active_output = None
        self._pending_resurface = True
        self._host.hide_window()
        self._release_blur()
        self._host.destroy_surface()
        remaining = self._select_output(connected, configured_name)
        if remaining is not None:
            self._schedule_resurface(remaining)

    def output_added(self, connected: tuple[Output, ...], configured_name: str | None) -> None:
        if not connected:
            return
        configured = next((output for output in connected if output.name == configured_name), None)
        if not self._pending_resurface and (
            configured is None or self._active_output is not None and self._active_output.name == configured.name
        ):
            return
        output = self._select_output(connected, configured_name)
        if output is not None:
            self._schedule_resurface(output)

    @staticmethod
    def _select_output(outputs: tuple[Output, ...], configured_name: str | None) -> Output | None:
        if configured_name:
            configured = next((output for output in outputs if output.name == configured_name), None)
            if configured is not None:
                return configured
        return outputs[0] if outputs else None

    def _schedule_resurface(self, output: Output) -> None:
        # The flag stays set until a rebuild actually happens. Clearing it here
        # stranded the overlay when the scheduled output vanished inside the delay:
        # the second removal returns early (the surface is already released), the
        # scheduled rebuild finds its target gone, and nothing is left to tell the
        # next output_added that a rebuild is still owed.
        self._resurface_output = output
        self._resurface_timer.start()

    def _restore_pending_surface(self) -> None:
        output, self._resurface_output = self._resurface_output, None
        if output is None:
            return
        # The timer outlives the window it rebuilds: an output can return after the
        # overlay is closed, and calling the handler then reaches a deleted widget.
        if not self._host.is_alive():
            return
        self._active_output = output
        if self._output_handler is None:
            return
        if not self._output_handler(output):
            # No surface was rebuilt on the returning output, so a rebuild is still
            # owed; clearing the flag here would retire it with nothing retrying.
            return
        self._pending_resurface = False  # only a rebuild that happened clears it

    def begin_drag(self, local_position: WindowPoint, global_position: WindowPoint) -> DragStartResult:
        return self._drag_strategy.begin_drag(local_position, global_position)

    def update_drag(self, local_position: WindowPoint, global_position: WindowPoint) -> OverlayOperationResult:
        return self._drag_strategy.update_drag(local_position, global_position)

    def end_drag(self) -> None:
        self._drag_strategy.end_drag()
