"""Contracts describing platform features available to the overlay."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .native import LayerShellController


@dataclass(frozen=True, slots=True)
class OverlayCapabilities:
    """Platform features and the reasons individual features are unavailable."""

    layer_shell: bool
    blur: bool
    layer_shell_reason: str | None = None
    blur_reason: str | None = None

    @classmethod
    def from_controller(cls, controller: LayerShellController) -> OverlayCapabilities:
        layer_shell = controller.available
        blur = controller.blur_available
        return cls(
            layer_shell=layer_shell,
            blur=blur,
            layer_shell_reason=controller.disabled_reason,
            # The controller already reports which cause it is — session, bridge,
            # protocol or build — and the UI translates that. Replacing it with one
            # sentence here would collapse four distinct situations into one.
            blur_reason=controller.blur_disabled_reason,
        )
