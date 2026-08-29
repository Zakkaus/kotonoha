"""Application ownership and asynchronous persistence for lyric timing corrections."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from ..async_task import create_owned_task, wait_for_owned
from ..async_worker import BlockingWorkerPort
from ..display.offsets import TrackOffsetEntry, TrackOffsetKey, TrackOffsetSnapshot

logger = logging.getLogger(__name__)


class TrackOffsetWriter(Protocol):
    """Synchronous persistence boundary for one validated offset entry."""

    def upsert(self, entry: TrackOffsetEntry) -> None:
        """Insert or replace one validated correction."""
        ...


class TrackOffsetPersistenceState(StrEnum):
    """Observable state of the latest track-offset write."""

    IDLE = "idle"
    PENDING = "pending"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TrackOffsetPersistenceStatus:
    """Current write state and a safe diagnostic for the latest failure."""

    state: TrackOffsetPersistenceState
    error: str | None = None


class TrackOffsetService:
    """Own in-memory lyric timing corrections and their persistence lifecycle."""

    def __init__(
        self,
        snapshot: TrackOffsetSnapshot,
        *,
        writer: TrackOffsetWriter,
        worker: BlockingWorkerPort,
    ) -> None:
        """Create a service without opening files or scheduling background work."""
        if not isinstance(snapshot, TrackOffsetSnapshot):
            raise TypeError("track offset service requires a TrackOffsetSnapshot")
        self._snapshot = snapshot
        self._writer = writer
        self._worker = worker
        self._pending_entries: dict[TrackOffsetKey, TrackOffsetEntry] = {}
        self._save_task: asyncio.Task[None] | None = None
        self._persistence_status = TrackOffsetPersistenceStatus(TrackOffsetPersistenceState.IDLE)
        self._closed = False

    def snapshot(self) -> TrackOffsetSnapshot:
        """Return the immutable corrections currently used by display projection."""
        return self._snapshot

    def offset_for(self, key: TrackOffsetKey) -> int:
        """Return the correction for one structured lyric timeline identity."""
        return self._snapshot.offset_for(key)

    @property
    def persistence_status(self) -> TrackOffsetPersistenceStatus:
        """Return whether the latest correction is pending, saved, or failed."""
        return self._persistence_status

    def set_offset(self, key: TrackOffsetKey, offset_ms: int) -> TrackOffsetSnapshot:
        """Update one correction and schedule persistence of the changed entry."""
        self._ensure_open()
        entry = TrackOffsetEntry(key, offset_ms)
        self._snapshot = self._snapshot.with_entry(entry)
        self._schedule_persist(entry)
        return self._snapshot

    def retry_persistence(self) -> None:
        """Retry the entries still pending after an observable failure."""
        self._ensure_open()
        if self._persistence_status.state is not TrackOffsetPersistenceState.FAILED or not self._pending_entries:
            return
        self._schedule_persist()

    async def flush(self) -> None:
        """Wait for the currently scheduled write without closing the service."""
        self._ensure_open()
        task = self._save_task
        if task is not None and await wait_for_owned(task):
            raise asyncio.CancelledError

    async def close(self) -> None:
        """Wait for the latest scheduled write and release the worker."""
        if self._closed:
            return
        self._closed = True
        task = self._save_task
        cancellation_requested = False
        try:
            if task is not None:
                cancellation_requested = await wait_for_owned(task)
        finally:
            self._worker.close()
        if cancellation_requested:
            raise asyncio.CancelledError

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("track offset service is closed")

    def _schedule_persist(self, entry: TrackOffsetEntry | None = None) -> None:
        """Schedule latest values for changed keys through one owned writer task."""
        if entry is not None:
            self._pending_entries[entry.key] = entry
        self._persistence_status = TrackOffsetPersistenceStatus(TrackOffsetPersistenceState.PENDING)
        task = self._save_task
        if task is not None and not task.done():
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            self._drain_persistence_sync()
            return
        task = create_owned_task(self._drain_persistence(), name="kotonoha-track-offset-save")
        self._save_task = task
        task.add_done_callback(self._persistence_finished)

    def _drain_persistence_sync(self) -> None:
        """Flush pending entries for synchronous callers outside an event loop."""
        while self._pending_entries:
            key, entry = next(iter(self._pending_entries.items()))
            try:
                self._writer.upsert(entry)
            except (OSError, RuntimeError, ValueError) as exc:
                self._persistence_status = TrackOffsetPersistenceStatus(
                    TrackOffsetPersistenceState.FAILED,
                    str(exc),
                )
                logger.warning("Could not save track offset: %s", exc)
                return
            if self._pending_entries.get(key) is entry:
                del self._pending_entries[key]
        self._persistence_status = TrackOffsetPersistenceStatus(TrackOffsetPersistenceState.IDLE)

    async def _drain_persistence(self) -> None:
        while self._pending_entries:
            key, entry = next(iter(self._pending_entries.items()))
            try:
                await self._worker.run(self._writer.upsert, entry)
            except asyncio.CancelledError:
                raise
            except (OSError, RuntimeError, ValueError) as exc:
                self._persistence_status = TrackOffsetPersistenceStatus(
                    TrackOffsetPersistenceState.FAILED,
                    str(exc),
                )
                logger.warning("Could not save track offset: %s", exc)
                return
            if self._pending_entries.get(key) is entry:
                del self._pending_entries[key]
            if not self._pending_entries:
                self._persistence_status = TrackOffsetPersistenceStatus(TrackOffsetPersistenceState.IDLE)

    def _persistence_finished(self, task: asyncio.Task[None]) -> None:
        """Retrieve unexpected worker failures so they cannot become lost task errors."""
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self._persistence_status = TrackOffsetPersistenceStatus(
                TrackOffsetPersistenceState.FAILED,
                str(error),
            )
            logger.warning("Track-offset persistence task failed: %s", error)


__all__ = [
    "TrackOffsetPersistenceState",
    "TrackOffsetPersistenceStatus",
    "TrackOffsetService",
    "TrackOffsetWriter",
]
