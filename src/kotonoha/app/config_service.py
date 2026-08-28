"""Application-scoped ownership for mutable configuration and persistence."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from ..async_task import create_owned_task, wait_for_owned
from ..async_worker import BlockingWorkerPort
from ..config import Config, set_track_offset
from ..config.schema import SETTINGS_CONFIG_FIELDS
from .config_merge import merge_settings

logger = logging.getLogger(__name__)


class ConfigPersistenceState(StrEnum):
    """Observable state of the latest configuration write."""

    IDLE = "idle"
    PENDING = "pending"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ConfigPersistenceStatus:
    """Current write state and a safe diagnostic for the last failure."""

    state: ConfigPersistenceState
    error: str | None = None


class ConfigWriter(Protocol):
    """Synchronous file boundary used by the application config owner."""

    def save(self, config: Config) -> None:
        """Persist one validated configuration."""
        ...


class ConfigService:
    """Own the one mutable application configuration instance.

    The composition root creates one instance and injects it into collaborators.
    Other components request changes through the typed methods below instead of
    mutating the shared model or calling the file store themselves. Persistence
    runs in the injected worker so Qt and the asyncio event loop stay responsive.
    """

    def __init__(
        self,
        config: Config,
        *,
        writer: ConfigWriter,
        worker: BlockingWorkerPort,
    ) -> None:
        self._config = config.clamped()
        self._writer = writer
        self._worker = worker
        self._pending_config: Config | None = None
        self._save_task: asyncio.Task[None] | None = None
        self._persistence_status = ConfigPersistenceStatus(ConfigPersistenceState.IDLE)
        self._closed = False

    @property
    def config(self) -> Config:
        """Return a detached view of the current application configuration."""
        return self._config.clamped()

    @property
    def persistence_status(self) -> ConfigPersistenceStatus:
        """Return whether the latest mutation is pending, saved, or failed."""
        return self._persistence_status

    def replace(self, config: Config) -> Config:
        """Replace settings, apply validation, and schedule immediate persistence."""
        self._ensure_open()
        self._config = config.clamped()
        self._schedule_persist()
        return self.config

    def apply_settings(
        self,
        config: Config,
        changed_fields: frozenset[str] = frozenset(SETTINGS_CONFIG_FIELDS),
    ) -> Config:
        """Merge submitted Settings values into the latest owned configuration.

        A Settings dialog may contain values from before a runtime drag or
        passthrough toggle. Only fields changed by that form are accepted, so
        newer runtime-owned values remain authoritative without a second config
        snapshot or a patch object.
        """
        self._ensure_open()
        if not changed_fields:
            return self.config
        self._config = merge_settings(self._config, config, changed_fields)
        self._schedule_persist()
        return self.config

    def set_passthrough(self, enabled: bool) -> Config:
        """Update the click-through setting and persist it."""
        self._ensure_open()
        self._config = replace(self._config, passthrough=bool(enabled)).clamped()
        self._schedule_persist()
        return self.config

    def set_position(
        self,
        margin_edge: int,
        margin_x: int,
        screen_name: str,
        screen_width: int,
        screen_height: int,
    ) -> Config:
        """Commit output-local placement settings and persist them."""
        self._ensure_open()
        self._config = replace(
            self._config,
            margin_edge=margin_edge,
            margin_x=margin_x,
            screen_name=screen_name,
            screen_width=screen_width,
            screen_height=screen_height,
        ).clamped()
        self._schedule_persist()
        return self.config

    def set_track_offset(self, key: str, offset_ms: int) -> Config:
        """Commit one track offset and persist the updated configuration."""
        self._ensure_open()
        updated = self._config.clamped()
        set_track_offset(updated, key, offset_ms)
        self._config = updated.clamped()
        self._schedule_persist()
        return self.config

    def retry_persistence(self) -> None:
        """Retry writing the current configuration after an observable failure."""
        self._ensure_open()
        self._schedule_persist()

    async def flush(self) -> None:
        """Wait for the currently scheduled write without closing the service."""
        self._ensure_open()
        task = self._save_task
        if task is not None:
            # A caller may cancel its wait, but the service still owns the save
            # task and must not lose the latest configuration as a side effect.
            if await wait_for_owned(task):
                raise asyncio.CancelledError

    async def close(self) -> None:
        """Wait for the latest scheduled save and release the worker."""
        if self._closed:
            return
        self._closed = True
        task = self._save_task
        cancellation_requested = False
        try:
            if task is not None:
                # Complete the owned write before releasing its worker, then
                # restore caller cancellation below.
                cancellation_requested = await wait_for_owned(task)
        finally:
            self._worker.close()
        if cancellation_requested:
            raise asyncio.CancelledError

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("configuration service is closed")

    def _schedule_persist(self) -> None:
        """Schedule one latest-value writer owned by this service."""
        self._pending_config = self._persistence_copy()
        self._persistence_status = ConfigPersistenceStatus(ConfigPersistenceState.PENDING)
        task = self._save_task
        if task is not None and not task.done():
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # Synchronous callers are limited to tests and early startup paths;
            # production UI callbacks run inside qasync and use the worker task.
            pending = self._pending_config
            self._pending_config = None
            if pending is None:
                return
            try:
                self._writer.save(pending)
            except (OSError, RuntimeError, ValueError) as exc:
                self._persistence_status = ConfigPersistenceStatus(
                    ConfigPersistenceState.FAILED,
                    str(exc),
                )
                logger.warning("Could not save config: %s", exc)
                return
            self._pending_config = None
            self._persistence_status = ConfigPersistenceStatus(ConfigPersistenceState.IDLE)
            return
        task = create_owned_task(self._drain_persistence(), name="kotonoha-config-save")
        self._save_task = task
        task.add_done_callback(self._persistence_finished)

    async def _drain_persistence(self) -> None:
        while self._pending_config is not None:
            config = self._pending_config
            try:
                await self._worker.run(self._writer.save, config)
            except asyncio.CancelledError:
                raise
            except (OSError, RuntimeError, ValueError) as exc:
                self._persistence_status = ConfigPersistenceStatus(
                    ConfigPersistenceState.FAILED,
                    str(exc),
                )
                logger.warning("Could not save config: %s", exc)
                return
            if self._pending_config is config:
                self._pending_config = None
                self._persistence_status = ConfigPersistenceStatus(ConfigPersistenceState.IDLE)

    def _persistence_finished(self, task: asyncio.Task[None]) -> None:
        """Retrieve unexpected worker failures so they cannot become lost task errors."""
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self._persistence_status = ConfigPersistenceStatus(
                ConfigPersistenceState.FAILED,
                str(error),
            )
            logger.warning("Configuration persistence task failed: %s", error)

    def _persistence_copy(self) -> Config:
        """Detach the worker input without exposing a second config owner."""
        return Config.from_dict(self._config.to_dict())


__all__ = [
    "ConfigPersistenceState",
    "ConfigPersistenceStatus",
    "ConfigService",
    "ConfigWriter",
]
