"""Own the overlay surface lifecycle and output-rebind state machine."""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject, QTimer

from .overlay_contracts import (
    Output,
    OutputBindingPort,
    SurfacePort,
    SurfaceResult,
    SurfaceState,
)

DEFAULT_RETRY_DELAY_MS = 250


class SurfaceLifecycleOwner:
    """Coordinate surface resources, output intent, retry and shutdown.

    The owner is the only component that changes the logical active output. A
    platform adapter may release the current native surface, but it cannot commit a
    new output or call back into a widget to rebuild one.
    """

    def __init__(
        self,
        surface: SurfacePort,
        *,
        output_binding: OutputBindingPort | None,
        timer_parent: QObject,
        rebuild_surface: Callable[[Output], SurfaceResult],
        on_rebind_applied: Callable[[Output], None] | None = None,
        retry_delay_ms: int = DEFAULT_RETRY_DELAY_MS,
    ) -> None:
        """Create an owner with explicit resource and rebuild collaborators."""
        if retry_delay_ms <= 0:
            raise ValueError("retry_delay_ms must be positive")
        self._surface = surface
        self._output_binding = output_binding
        self._rebuild_surface = rebuild_surface
        self._on_rebind_applied = on_rebind_applied
        self._retry_delay_ms = retry_delay_ms
        self._state = SurfaceState.UNPREPARED
        self._active_output: Output | None = None
        self._pending_output: Output | None = None
        self._surface_released = False
        self._retry_timer = QTimer(timer_parent)
        self._retry_timer.setSingleShot(True)
        self._retry_timer.timeout.connect(self._retry_pending_surface)

    @property
    def state(self) -> SurfaceState:
        """Return the current lifecycle state."""
        return self._state

    @property
    def active_output(self) -> Output | None:
        """Return the last output whose surface rebuild actually succeeded."""
        return self._active_output

    @property
    def pending_output(self) -> Output | None:
        """Return the output intent retained after a deferred or failed rebind."""
        return self._pending_output

    @property
    def retry_timer(self) -> QTimer:
        """Expose the owned timer for deterministic lifecycle tests."""
        return self._retry_timer

    def prepare(self) -> SurfaceResult:
        """Prepare the native surface, transitioning to ``Prepared`` on success."""
        if self._state in {SurfaceState.CLOSING, SurfaceState.CLOSED}:
            return SurfaceResult.rejected("The overlay surface is closed.")
        if self._state in {SurfaceState.PREPARED, SurfaceState.ACTIVE, SurfaceState.REBINDING}:
            return SurfaceResult.applied()
        result = self._surface.prepare()
        self._state = SurfaceState.PREPARED if result.succeeded else SurfaceState.DEGRADED
        return result

    def activate(self, output: Output | None) -> SurfaceResult:
        """Map the surface and commit its output only after activation succeeds."""
        if self._state in {SurfaceState.CLOSING, SurfaceState.CLOSED}:
            return SurfaceResult.rejected("The overlay surface is closed.")
        if self._state is SurfaceState.ACTIVE:
            if output is None or self._active_output is None or output.name == self._active_output.name:
                return SurfaceResult.applied()
            return self.rebind(output)
        if self._state is SurfaceState.REBINDING:
            if self._pending_output is None:
                return SurfaceResult.rejected("No output is available for surface activation.")
            return self._attempt_pending_rebind()
        if self._state is SurfaceState.DEGRADED and self._pending_output is not None:
            return self._attempt_pending_rebind()
        if self._state in {SurfaceState.UNPREPARED, SurfaceState.DEGRADED}:
            prepared = self.prepare()
            if not prepared.succeeded:
                return prepared
        result = self._surface.activate()
        if not result.succeeded:
            self._state = SurfaceState.DEGRADED
            return result
        self._surface_released = False
        self._active_output = output
        self._pending_output = None
        self._state = SurfaceState.ACTIVE
        self._retry_timer.stop()
        return result

    def rebind(self, output: Output) -> SurfaceResult:
        """Recreate the surface on ``output`` and retain intent on failure."""
        if self._state in {SurfaceState.CLOSING, SurfaceState.CLOSED}:
            return SurfaceResult.rejected("The overlay surface is closed.")
        if self._output_binding is None or not self._surface.capabilities.output_rebinding:
            return SurfaceResult.not_supported(
                self._surface.capabilities.output_rebinding_reason or "Output rebinding is unavailable."
            )
        self._pending_output = output
        self._state = SurfaceState.REBINDING
        self._retry_timer.stop()
        released = self._release_for_rebind()
        if not released.succeeded:
            self._state = SurfaceState.DEGRADED
            self._schedule_retry_if_needed(released)
            return released
        return self._attempt_pending_rebind()

    def output_removed(self, output: Output, replacement: Output | None) -> None:
        """Release a removed active output and retain the replacement intent."""
        if self._output_binding is None or not self._surface.capabilities.output_rebinding:
            return
        if self._pending_output is not None and self._pending_output.name == output.name:
            self._pending_output = replacement
        if self._active_output is None or self._active_output.name != output.name:
            return
        self._active_output = None
        self._pending_output = replacement
        self._state = SurfaceState.REBINDING
        released = self._release_for_rebind()
        if not released.succeeded:
            self._state = SurfaceState.DEGRADED
            self._schedule_retry_if_needed(released)
            return
        if replacement is not None:
            self._schedule_retry()

    def output_added(self, output: Output) -> None:
        """Replace a pending output with a connected candidate and schedule retry."""
        if self._state in {SurfaceState.CLOSING, SurfaceState.CLOSED}:
            return
        if self._state not in {SurfaceState.REBINDING, SurfaceState.DEGRADED}:
            return
        self._pending_output = output
        self._state = SurfaceState.REBINDING
        self._schedule_retry()

    def retry_pending(self) -> SurfaceResult:
        """Attempt the retained output intent immediately for tests or an event."""
        return self._attempt_pending_rebind()

    def close(self) -> SurfaceResult:
        """Stop deferred work and release the surface exactly once."""
        if self._state is SurfaceState.CLOSED:
            return SurfaceResult.applied()
        self._state = SurfaceState.CLOSING
        self._retry_timer.stop()
        self._pending_output = None
        result = self._surface.close()
        if result.succeeded:
            self._surface_released = True
            self._active_output = None
            self._state = SurfaceState.CLOSED
        return result

    def _release_for_rebind(self) -> SurfaceResult:
        """Release old-surface resources without closing the adapter."""
        if self._surface_released:
            return SurfaceResult.applied()
        if self._output_binding is None:
            return SurfaceResult.not_supported("Output rebinding is unavailable.")
        result = self._output_binding.release_for_output_rebind()
        if result.succeeded:
            self._surface_released = True
        return result

    def _attempt_pending_rebind(self) -> SurfaceResult:
        """Run one guarded rebuild attempt and preserve failed intent."""
        if self._state in {SurfaceState.CLOSING, SurfaceState.CLOSED}:
            return SurfaceResult.rejected("The overlay surface is closed.")
        output = self._pending_output
        if output is None:
            return SurfaceResult.rejected("No output rebind is pending.")
        if not self._surface_released:
            released = self._release_for_rebind()
            if not released.succeeded:
                self._state = SurfaceState.DEGRADED
                self._schedule_retry_if_needed(released)
                return released
        self._state = SurfaceState.REBINDING
        result = self._rebuild_surface(output)
        if result.succeeded:
            self._active_output = output
            self._pending_output = None
            self._surface_released = False
            self._state = SurfaceState.ACTIVE
            self._retry_timer.stop()
            if self._on_rebind_applied is not None:
                self._on_rebind_applied(output)
            return result
        # The rebuild callback owns a platform-specific partial construction. Even
        # when it cleaned that construction up, the owner must verify release on the
        # next attempt; treating the previous pre-image release as current would
        # allow a half-built surface to survive a retry.
        self._surface_released = False
        self._state = SurfaceState.DEGRADED
        self._schedule_retry_if_needed(result)
        return result

    def _schedule_retry_if_needed(self, result: SurfaceResult) -> None:
        """Retry only failures explicitly marked retryable; output events handle absence."""
        if result.retryable and self._pending_output is not None:
            self._schedule_retry()

    def _schedule_retry(self) -> None:
        """Arm the owner-owned timer while retaining the pending output."""
        if self._state not in {SurfaceState.REBINDING, SurfaceState.DEGRADED}:
            return
        if self._pending_output is not None:
            self._retry_timer.start(self._retry_delay_ms)

    def _retry_pending_surface(self) -> None:
        """Handle a timer callback without touching a closed surface."""
        if self._state in {SurfaceState.CLOSING, SurfaceState.CLOSED}:
            return
        self._attempt_pending_rebind()


__all__ = ["DEFAULT_RETRY_DELAY_MS", "SurfaceLifecycleOwner"]
