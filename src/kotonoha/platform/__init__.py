"""Platform integration for overlay capabilities and native bridges."""

from .layer_shell import LayerShellPlatform
from .native import LayerShellController, default_package_dir
from .overlay_contracts import (
    BlurPort,
    DragMode,
    DragPort,
    DragStartResult,
    InputRegionPort,
    Output,
    OutputBindingPort,
    OverlayCapabilities,
    OverlayPlatform,
    OverlayPlatformAdapters,
    OverlayPlatformFactory,
    PlacementPort,
    SurfacePort,
    SurfaceResult,
    SurfaceResultStatus,
    SurfaceState,
    WindowHost,
    WindowPoint,
    WindowPolicy,
    WindowRectangle,
)
from .qt_host import QtWindowHost
from .surface_lifecycle import SurfaceLifecycleOwner
from .window_platform import DefaultOverlayPlatformFactory

__all__ = [
    "DefaultOverlayPlatformFactory",
    "BlurPort",
    "DragMode",
    "DragPort",
    "DragStartResult",
    "InputRegionPort",
    "LayerShellController",
    "OverlayCapabilities",
    "OverlayPlatform",
    "OverlayPlatformAdapters",
    "OverlayPlatformFactory",
    "Output",
    "OutputBindingPort",
    "PlacementPort",
    "SurfaceLifecycleOwner",
    "SurfacePort",
    "SurfaceResult",
    "SurfaceResultStatus",
    "SurfaceState",
    "WindowHost",
    "WindowPoint",
    "WindowPolicy",
    "WindowRectangle",
    "QtWindowHost",
    "LayerShellPlatform",
    "default_package_dir",
]
