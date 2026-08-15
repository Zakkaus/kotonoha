"""Ordered providers for selecting Kotonoha's overlay platform adapter."""

from __future__ import annotations

from typing import Protocol

from PyQt6.QtGui import QGuiApplication

from .detect import current_desktop, session_desktop
from .layer_shell import LayerShellAnchorDragStrategy, LayerShellPlatform, NiriLayerShellDragStrategy
from .native import LayerShellController, default_package_dir
from .overlay_contracts import LayerShellBridge, OverlayDragStrategy, OverlayPlatform, WindowHost
from .qt_window import QtWindowPlatform


class _Provider(Protocol):
    def select(self, platform_name: str, desktop: str, host: WindowHost) -> OverlayPlatform | None: ...

class _LayerShellDragProvider(Protocol):
    """Create a strategy when a Layer Shell compositor is recognized."""

    def create(self, desktop: str, host: WindowHost, controller: LayerShellBridge) -> OverlayDragStrategy | None: ...


class _NiriLayerShellDragProvider:
    """Select global-delta dragging for niri's asynchronous configure behavior."""

    def create(self, desktop: str, host: WindowHost, controller: LayerShellBridge) -> OverlayDragStrategy | None:
        desktops = {part.strip().lower() for part in desktop.split(":")}
        if "niri" not in desktops:
            return None
        return NiriLayerShellDragStrategy(host, controller)


class _DefaultLayerShellDragProvider:
    """Provide the existing local-anchor model for unrecognized compositors."""

    def create(self, desktop: str, host: WindowHost, controller: LayerShellBridge) -> OverlayDragStrategy | None:
        del desktop
        return LayerShellAnchorDragStrategy(host, controller)


class _LayerShellProvider:
    def __init__(
        self,
        controller: LayerShellBridge,
        drag_providers: tuple[_LayerShellDragProvider, ...] | None = None,
    ) -> None:
        self._controller = controller
        self._drag_providers = drag_providers or (_NiriLayerShellDragProvider(), _DefaultLayerShellDragProvider())

    def select(self, platform_name: str, desktop: str, host: WindowHost) -> OverlayPlatform | None:
        # The controller has already asked the compositor, and its probe outranks the
        # desktop name — checking the name again here demoted a session that does
        # advertise zwlr_layer_shell_v1 to an ordinary window, losing stacking,
        # precise placement and output binding. The name check remains inside the
        # controller as the fallback for a bridge too old to expose the probe.
        #
        # The name still selects the *drag* strategy below: no protocol reports
        # which compositor this is, and the two behaviours differ by compositor.
        if not platform_name.startswith("wayland") or not self._controller.available:
            return None
        for provider in self._drag_providers:
            strategy = provider.create(desktop, host, self._controller)
            if strategy is not None:
                return LayerShellPlatform(host, self._controller, strategy)
        return LayerShellPlatform(host, self._controller)


class _X11Provider:
    def __init__(self, controller: LayerShellBridge | None = None) -> None:
        self._controller = controller

    def select(self, platform_name: str, desktop: str, host: WindowHost) -> OverlayPlatform | None:
        del desktop
        if platform_name != "xcb":
            return None
        return QtWindowPlatform(
            host, reason="X11 has no Layer Shell overlay capability.", blur=self._controller
        )


class _WaylandFallbackProvider:
    def __init__(self, controller: LayerShellBridge | None = None) -> None:
        self._controller = controller

    def select(self, platform_name: str, desktop: str, host: WindowHost) -> OverlayPlatform | None:
        del desktop
        if not platform_name.startswith("wayland"):
            return None
        # Still hand over the bridge: a Wayland compositor without Layer Shell can
        # speak a blur protocol, which is exactly the Mutter case.
        return QtWindowPlatform(
            host,
            reason="Wayland compositor does not provide Layer Shell.",
            blur=self._controller,
            # Wayland gives a client no way to place its own toplevel, and no
            # readback can tell: Qt reports the requested position either way.
            client_positioning=False,
            # Nor a way to set the window's opacity.
            window_opacity=False,
        )


class _GenericFallbackProvider:
    def __init__(self, controller: LayerShellBridge | None = None) -> None:
        self._controller = controller

    def select(self, platform_name: str, desktop: str, host: WindowHost) -> OverlayPlatform:
        del platform_name, desktop
        return QtWindowPlatform(
            host, reason="Layer Shell is unavailable on this platform.", blur=self._controller
        )


class DefaultOverlayPlatformFactory:
    """Select the first claiming provider: Layer Shell, X11, Wayland, generic."""

    def __init__(
        self,
        controller: LayerShellBridge | None = None,
        *,
        platform_name: str | None = None,
        current_desktop: str | None = None,
        providers: tuple[_Provider, ...] | None = None,
    ) -> None:
        self._controller = controller or LayerShellController(
            default_package_dir(),
            platform_name or QGuiApplication.platformName(),
            current_desktop or self._current_desktop(),
        )
        self._platform_name = platform_name
        self._current_desktop_value = current_desktop
        self._providers = providers or (
            _LayerShellProvider(self._controller),
            _X11Provider(self._controller),
            _WaylandFallbackProvider(self._controller),
            _GenericFallbackProvider(self._controller),
        )

    def __call__(self, host: WindowHost) -> OverlayPlatform:
        platform_name = self._platform_name or QGuiApplication.platformName()
        desktop = self._current_desktop_value or self._current_desktop()
        for provider in self._providers:
            platform = provider.select(platform_name, desktop, host)
            if platform is not None:
                return platform
        raise RuntimeError("No overlay platform provider claimed the session.")

    @staticmethod
    def _current_desktop() -> str:
        app = QGuiApplication.instance()
        qt_desktop = str(app.property("xdg_current_desktop") or "") if app is not None else ""
        detected_desktops = (current_desktop(), session_desktop())
        return ":".join(value for value in (qt_desktop, *detected_desktops) if value)
