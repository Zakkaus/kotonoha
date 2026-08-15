"""Platform integration for overlay capabilities and native bridges."""

from .native import LayerShellController, default_package_dir
from .overlay_contracts import OverlayCapabilities

__all__ = ["LayerShellController", "OverlayCapabilities", "default_package_dir"]
