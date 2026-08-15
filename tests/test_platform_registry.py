"""Ordered overlay-platform provider selection without a compositor."""

from __future__ import annotations

from kotonoha.platform.layer_shell import LayerShellPlatform
from kotonoha.platform.overlay_contracts import WindowPoint, WindowPolicy, WindowRectangle
from kotonoha.platform.qt_window import QtWindowPlatform
from kotonoha.platform.window_platform import DefaultOverlayPlatformFactory


class _FakeController:
    """Stands in for the native bridge, so a session can be described without ctypes."""

    def __init__(self, available: bool, blur_available: bool = False) -> None:
        self.available = available
        self.blur_available = blur_available
        self.disabled_reason = None if available else "Fake compositor rejected Layer Shell."
        self.blur_disabled_reason = None if blur_available else "protocol"
        self.calls: list[tuple[str, tuple[int, ...]]] = []

    def make_overlay(self, window_ptr: int) -> None:
        self.calls.append(("make_overlay", (window_ptr,)))

    def set_passthrough(self, window_ptr: int, enabled: bool) -> None:
        self.calls.append(("set_passthrough", (window_ptr, int(enabled))))

    def set_input_rect(self, window_ptr: int, x: int, y: int, w: int, h: int) -> None:
        self.calls.append(("set_input_rect", (window_ptr, x, y, w, h)))

    def set_anchor_position(self, window_ptr: int, x: int, y: int) -> None:
        self.calls.append(("set_anchor_position", (window_ptr, x, y)))

    def set_blur_region(self, window_ptr: int, x: int, y: int, w: int, h: int, radius: int) -> None:
        self.calls.append(("set_blur_region", (window_ptr, x, y, w, h, radius)))

    def clear_blur(self, window_ptr: int) -> None:
        self.calls.append(("clear_blur", (window_ptr,)))


class _FakeHost:
    def __init__(self) -> None:
        self.masks: list[object] = []
        self.policies: list[WindowPolicy] = []

    def apply_window_policy(self, policy: WindowPolicy) -> None:
        self.policies.append(policy)

    def set_input_mask(self, region: WindowRectangle) -> None:
        self.masks.append(region)

    def clear_input_mask(self) -> None:
        self.masks.append("cleared")

    def native_window_pointer(self) -> int | None:
        return 1

    def geometry(self) -> WindowRectangle:
        return WindowRectangle(0, 0, 100, 50)

    def window_position(self) -> WindowPoint | None:
        return WindowPoint(0, 0)

    def screen_geometry(self) -> WindowRectangle | None:
        return WindowRectangle(0, 0, 1920, 1080)

    def bind_output(self, output: WindowRectangle) -> None:
        del output

    def move_window(self, position: WindowPoint) -> None:
        del position

    def refresh(self) -> None:
        pass


def test_provider_order_selects_layer_shell_before_fallbacks() -> None:
    platform = DefaultOverlayPlatformFactory(
        _FakeController(available=True, blur_available=True), platform_name="wayland", current_desktop="KDE"
    )(_FakeHost())

    assert isinstance(platform, LayerShellPlatform)
    assert platform.capabilities.layer_shell
    assert platform.capabilities.blur


def test_x11_provider_claims_without_layer_shell() -> None:
    platform = DefaultOverlayPlatformFactory(_FakeController(False), platform_name="xcb")(_FakeHost())

    assert isinstance(platform, QtWindowPlatform)
    assert not platform.capabilities.layer_shell
    assert platform.capabilities.layer_shell_reason == "X11 has no Layer Shell overlay capability."


def test_wayland_fallback_explains_rejected_layer_shell() -> None:
    platform = DefaultOverlayPlatformFactory(
        _FakeController(False), platform_name="wayland", current_desktop="GNOME"
    )(_FakeHost())

    assert isinstance(platform, QtWindowPlatform)
    assert platform.capabilities.layer_shell_reason == "Wayland compositor does not provide Layer Shell."
    assert platform.capabilities.blur_reason == "Ordinary windows cannot request compositor backdrop blur."


def test_generic_provider_claims_unknown_platform_with_reason() -> None:
    platform = DefaultOverlayPlatformFactory(_FakeController(False), platform_name="offscreen")(_FakeHost())

    assert isinstance(platform, QtWindowPlatform)
    assert platform.capabilities.layer_shell_reason == "Layer Shell is unavailable on this platform."


def test_the_fallback_shapes_its_input_region_to_the_rectangle() -> None:
    # Only the whole-window pass-through switch was applied before, so an unlocked
    # ordinary window kept accepting clicks across its whole transparent area and
    # swallowed input meant for the window behind it.
    host = _FakeHost()
    platform = QtWindowPlatform(host, reason="no Layer Shell here")

    assert platform.set_input_region(WindowRectangle(4, 6, 40, 20)).succeeded

    # Unlocked: input is confined to the rectangle, and the window is not made
    # transparent to the pointer.
    assert host.masks == [WindowRectangle(4, 6, 40, 20)]
    assert host.policies[-1].mouse_events_transparent is False

    assert platform.set_input_region(None).succeeded

    # Locked: click-through is carried by the policy flag, and the shaping is
    # cleared rather than set to nothing — the two must not disagree.
    assert host.masks[-1] == "cleared"
    assert host.policies[-1].mouse_events_transparent is True


def test_layer_shell_operations_report_failure_when_the_capability_is_off() -> None:
    # The bridge no-ops silently when Layer Shell is unavailable, so reporting
    # success told the caller an update had happened that had not.
    platform = LayerShellPlatform(_FakeHost(), _FakeController(available=False))

    for result in (
        platform.set_input_region(WindowRectangle(0, 0, 10, 10)),
        platform.move_to(WindowPoint(1, 2)),
        platform.rebind_output(WindowRectangle(0, 0, 800, 600)),
    ):
        assert not result.succeeded
        assert result.reason
