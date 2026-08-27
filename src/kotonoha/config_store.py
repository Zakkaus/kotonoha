"""File-backed configuration storage.

The :class:`Config` model owns validation and serialization. This module owns
the filesystem boundary: locating the XDG file, bounding untrusted reads,
salvaging invalid JSON, and replacing files atomically.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from .config import Config

logger = logging.getLogger(__name__)

APP_DIR_NAME = "kotonoha"
CONFIG_FILE_NAME = "config.json"

# A settings file is a few kilobytes. The read is bounded because this path is
# reachable by anything with write access to the user's config directory.
MAX_CONFIG_BYTES: Final[int] = 4 * 1024 * 1024


def config_dir() -> Path:
    """Return the application configuration directory under XDG settings."""
    base = os.environ.get("XDG_CONFIG_HOME")
    if base is None or not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / APP_DIR_NAME


def config_path() -> Path:
    """Return the default configuration file path."""
    return config_dir() / CONFIG_FILE_NAME


def _read_config_bytes(target: Path) -> bytes | None:
    """Read one ordinary configuration file without blocking or over-reading.

    FIFOs and other non-regular files are rejected before any content is read.
    Missing, inaccessible, or otherwise unusable files return ``None`` so the
    application can start with defaults.
    """
    try:
        descriptor = os.open(target, os.O_RDONLY | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("Could not read config %s: %s", target, exc)
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            logger.warning("Config %s is not an ordinary file; using defaults", target)
            return None
        if os.fstat(descriptor).st_size > MAX_CONFIG_BYTES:
            logger.warning("Config %s exceeds %d bytes; using defaults", target, MAX_CONFIG_BYTES)
            return None
        chunks: list[bytes] = []
        remaining = MAX_CONFIG_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 1 << 16))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > MAX_CONFIG_BYTES:
            logger.warning("Config %s exceeds %d bytes; using defaults", target, MAX_CONFIG_BYTES)
            return None
    except OSError as exc:
        logger.warning("Could not read config %s: %s", target, exc)
        return None
    finally:
        os.close(descriptor)
    return data


class ConfigStore:
    """Load and save one typed configuration model at an explicit path.

    The path is optional so callers can use the XDG default, while tests and
    migrations can inject a concrete file without changing process state.
    """

    def __init__(self, config_type: type[Config], path: Path | None = None) -> None:
        self._config_type = config_type
        self._path = path

    def load(self) -> Config:
        """Return stored settings, or a fresh default model on read failure."""
        target = config_path() if self._path is None else self._path
        data = _read_config_bytes(target)
        if data is None:
            return self._config_type()
        try:
            raw = data.decode("utf-8")
        except UnicodeDecodeError:
            # The config is read before a window exists to report a problem. Treat
            # invalid encoding like invalid JSON and preserve the original file.
            raw = ""
        try:
            return self._config_type.from_dict(json.loads(raw))
        except (json.JSONDecodeError, ValueError):
            # Keep an unreadable file before returning defaults. Otherwise the next
            # save could overwrite every user setting after one interrupted write.
            salvaged = target.with_suffix(target.suffix + ".corrupt")
            try:
                target.replace(salvaged)
            except OSError as exc:
                logger.warning("Config %s is unreadable and could not be set aside: %s", target, exc)
            else:
                logger.warning("Config %s is not valid JSON; kept as %s and using defaults", target, salvaged)
            return self._config_type()

    def save(self, config: Config) -> None:
        """Persist settings with an fsynced sibling temporary and atomic rename."""
        target = config_path() if self._path is None else self._path
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(config.to_dict(), indent=2, ensure_ascii=False)
        # Created exclusively under an unpredictable name: a fixed one is a file
        # another process can replace with a symlink before the write.
        descriptor, temporary_name = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}.", suffix=".new"
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                # Rename orders against data actually taken by the filesystem.
                os.fsync(handle.fileno())
            temporary.replace(target)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise


__all__ = [
    "APP_DIR_NAME",
    "CONFIG_FILE_NAME",
    "ConfigStore",
    "MAX_CONFIG_BYTES",
    "config_dir",
    "config_path",
]
