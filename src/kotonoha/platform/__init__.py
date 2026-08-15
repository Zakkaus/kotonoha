"""Platform integration for overlay capabilities and native bridges."""

from .native import LayerShellController, default_package_dir
from .overlay_contracts import (
    OverlayCapabilities,
    OverlayOperationResult,
    OverlayPlatform,
    WindowHost,
    WindowPoint,
    WindowPolicy,
    WindowRectangle,
)
from .qt_host import QtWindowHost
from .window_platform import DefaultOverlayPlatformFactory

__all__ = [
    "DefaultOverlayPlatformFactory",
    "LayerShellController",
    "OverlayCapabilities",
    "OverlayOperationResult",
    "OverlayPlatform",
    "WindowHost",
    "WindowPoint",
    "WindowPolicy",
    "WindowRectangle",
    "QtWindowHost",
    "default_package_dir",
]
