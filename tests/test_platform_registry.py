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
    def apply_window_policy(self, policy: WindowPolicy) -> None:
        del policy

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
