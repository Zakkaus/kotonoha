"""Qt process adapter used by the application composition root."""

from __future__ import annotations

from collections.abc import Sequence

from PyQt6.QtCore import QProcess


class QProcessRestartLauncher:
    """Adapt Qt's detached-process API to the application restart port."""

    def start(self, executable: str, arguments: Sequence[str]) -> bool:
        """Return whether Qt accepted the replacement process request."""
        started, _pid = QProcess.startDetached(executable, list(arguments))
        return bool(started)


__all__ = ["QProcessRestartLauncher"]
