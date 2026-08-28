"""Application-facing contract for opening and observing the Settings dialog."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from ..config import Config
from ..players import PlayerInfo


class SignalPort(Protocol):
    """Minimal signal surface needed by application lifecycle code."""

    def connect(self, slot: Callable[..., object]) -> object:
        """Connect one application callback to the signal."""
        ...


class SettingsDialogPort(Protocol):
    """Non-Qt dialog operations used by the application controller."""

    @property
    def intent_requested(self) -> SignalPort:
        """Return the typed intent signal emitted by the dialog."""
        ...

    @property
    def finished(self) -> SignalPort:
        """Return the signal emitted when the dialog closes."""
        ...

    def show(self) -> None:
        """Show the ordinary, user-draggable Settings window."""
        ...

    def close(self) -> object:
        """Close the dialog and release its Qt resources."""
        ...

    def raise_(self) -> object:
        """Raise an already-open dialog without creating another one."""
        ...

    def activateWindow(self) -> object:
        """Request keyboard focus for the existing dialog."""
        ...


class SettingsDialogFactory(Protocol):
    """Create one presentation dialog for the current application state."""

    def create(self, config: Config, players: list[PlayerInfo]) -> SettingsDialogPort:
        """Create one dialog using the current config and player choices."""
        ...


__all__ = ["SettingsDialogFactory", "SettingsDialogPort", "SignalPort"]
