"""File-backed configuration storage.

The :class:`Config` model owns validation and serialization. This module owns
the filesystem boundary: locating the XDG file, bounding untrusted reads,
salvaging invalid JSON, and replacing files atomically.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Final

from ..file_access import BoundedRegularFileReader, RegularFileReadFailure
from .models import Config

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


class ConfigStore:
    """Load and save one typed configuration model at an explicit path.

    The path is optional so callers can use the XDG default, while tests and
    migrations can inject a concrete file without changing process state.
    """

    def __init__(self, config_type: type[Config], path: Path | None = None) -> None:
        self._config_type = config_type
        self._path = path
        self._reader = BoundedRegularFileReader(MAX_CONFIG_BYTES)

    def load(self) -> Config:
        """Return stored settings, or a fresh default model on read failure."""
        target = config_path() if self._path is None else self._path
        result = self._reader.read(target)
        data = result.data
        if data is None:
            if result.failure is not RegularFileReadFailure.MISSING:
                logger.warning("Could not read config %s: %s", target, result.failure)
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


def load_config(path: Path | None = None) -> Config:
    """Load configuration through the typed file-storage boundary."""
    return ConfigStore(Config, path).load()


def save_config(config: Config, path: Path | None = None) -> None:
    """Save configuration through the typed file-storage boundary."""
    ConfigStore(Config, path).save(config)


__all__ = [
    "APP_DIR_NAME",
    "CONFIG_FILE_NAME",
    "ConfigStore",
    "MAX_CONFIG_BYTES",
    "config_dir",
    "config_path",
    "load_config",
    "save_config",
]
