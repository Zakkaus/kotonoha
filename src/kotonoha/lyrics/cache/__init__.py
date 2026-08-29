"""Provider-scoped asynchronous cache facade for validated lyric artifacts."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path

from ...async_worker import BlockingWorkerPort
from ..artifact import LyricsArtifact
from ..match import MatchConfidence, TrackMetadata
from .models import (
    CacheDeleteResult,
    CacheDeleteStatus,
    CacheWriteResult,
    CacheWriteStatus,
    LyricsCacheEntry,
    LyricsCacheHit,
    LyricsCacheKey,
    LyricsCacheMode,
    LyricsCacheQuery,
)
from .storage import (
    CACHE_SCHEMA_VERSION,
    DEFAULT_MAX_ENTRIES,
    LyricsCacheStorage,
    PayloadParser,
    cache_path,
)


class LyricsCacheError(RuntimeError):
    """A cache operation failed behind the persistent-storage boundary."""


class LyricsCache:
    """Own the worker boundary around one synchronous SQLite cache storage."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        worker: BlockingWorkerPort,
    ) -> None:
        """Create a cache facade without opening a database or worker task."""
        self._worker = worker
        self._storage = LyricsCacheStorage(path or cache_path(), max_entries=max_entries)

    def start(self) -> None:
        """Reopen the owned worker after a previous provider shutdown."""
        self._worker.reopen()

    def close(self) -> None:
        """Release the cache worker; an already-running SQLite call may finish."""
        self._worker.close()

    async def lookup(
        self,
        provider: str,
        track: TrackMetadata,
        parser: PayloadParser,
    ) -> LyricsCacheHit | None:
        """Return one matching automatically stored artifact for a provider."""
        try:
            return await self._worker.run(self._storage.lookup, provider, track, parser)
        except (OSError, sqlite3.Error) as exc:
            raise LyricsCacheError("Lyrics cache lookup failed") from exc

    async def lookup_manual(
        self,
        track: TrackMetadata,
        parsers: Mapping[str, PayloadParser],
    ) -> LyricsCacheHit | None:
        """Return the latest matching manual selection across known providers."""
        try:
            return await self._worker.run(self._storage.lookup_manual, track, parsers)
        except (OSError, sqlite3.Error) as exc:
            raise LyricsCacheError("Manual lyrics cache lookup failed") from exc

    async def store(self, artifact: LyricsArtifact) -> CacheWriteResult | None:
        """Persist an automatically resolved artifact only at high confidence."""
        if artifact.confidence is MatchConfidence.HIGH:
            return await self.upsert(artifact, mode=LyricsCacheMode.AUTO)
        return None

    async def search(self, query: LyricsCacheQuery) -> tuple[LyricsCacheEntry, ...]:
        """Return matching cache metadata in deterministic recent-use order."""
        try:
            return await self._worker.run(self._storage.search, query)
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            raise LyricsCacheError("Lyrics cache search failed") from exc

    async def get(self, key: LyricsCacheKey) -> LyricsCacheEntry | None:
        """Return one cache entry by its provider-scoped key."""
        try:
            return await self._worker.run(self._storage.get, key)
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            raise LyricsCacheError("Lyrics cache read failed") from exc

    async def upsert(
        self,
        artifact: LyricsArtifact,
        *,
        mode: LyricsCacheMode = LyricsCacheMode.MANUAL,
    ) -> CacheWriteResult:
        """Create or replace a validated artifact for an explicit workflow."""
        _validate_artifact(artifact)
        _validate_mode(mode)
        try:
            return await self._worker.run(self._storage.upsert, artifact, mode)
        except (OSError, sqlite3.Error) as exc:
            raise LyricsCacheError("Lyrics cache write failed") from exc

    async def update(
        self,
        key: LyricsCacheKey,
        artifact: LyricsArtifact,
        *,
        mode: LyricsCacheMode = LyricsCacheMode.MANUAL,
    ) -> CacheWriteResult:
        """Update an existing entry and record the selection mode."""
        if key != LyricsCacheKey(artifact.provider, artifact.provider_song_id):
            raise ValueError("cache update key must match the artifact identity")
        _validate_artifact(artifact)
        _validate_mode(mode)
        try:
            return await self._worker.run(self._storage.update, key, artifact, mode)
        except (OSError, sqlite3.Error) as exc:
            raise LyricsCacheError("Lyrics cache update failed") from exc

    async def delete(self, key: LyricsCacheKey) -> CacheDeleteResult:
        """Delete one entry and report when it was already absent."""
        try:
            return await self._worker.run(self._storage.delete, key)
        except (OSError, sqlite3.Error) as exc:
            raise LyricsCacheError("Lyrics cache delete failed") from exc

    async def delete_many(self, keys: tuple[LyricsCacheKey, ...]) -> tuple[CacheDeleteResult, ...]:
        """Delete several exact entries in one owned SQLite operation."""
        try:
            return await self._worker.run(self._storage.delete_many, keys)
        except (OSError, sqlite3.Error) as exc:
            raise LyricsCacheError("Lyrics cache delete failed") from exc

    async def clear(self) -> None:
        """Delete every persisted lyric cache entry."""
        try:
            await self._worker.run(self._storage.clear)
        except (OSError, sqlite3.Error) as exc:
            raise LyricsCacheError("Lyrics cache clear failed") from exc

    async def count(self) -> int:
        """Return the number of persisted lyric cache entries."""
        try:
            return await self._worker.run(self._storage.count)
        except (OSError, sqlite3.Error) as exc:
            raise LyricsCacheError("Lyrics cache count failed") from exc


def _validate_artifact(artifact: LyricsArtifact) -> None:
    """Reject malformed write input before it reaches the persistence boundary."""
    if not artifact.provider or not artifact.provider_song_id:
        raise ValueError("cache artifacts require provider and provider song id")
    if not artifact.lines:
        raise ValueError("cache artifacts require timed lyric lines")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in artifact.payload.items()):
        raise TypeError("cache artifact payload must be a string map")


def _validate_mode(mode: LyricsCacheMode) -> None:
    """Reject untyped cache-mode values before they reach SQLite serialization."""
    if not isinstance(mode, LyricsCacheMode):
        raise TypeError("cache mode must be LyricsCacheMode")


__all__ = [
    "CACHE_SCHEMA_VERSION",
    "DEFAULT_MAX_ENTRIES",
    "CacheDeleteResult",
    "CacheDeleteStatus",
    "CacheWriteResult",
    "CacheWriteStatus",
    "LyricsCache",
    "LyricsCacheEntry",
    "LyricsCacheError",
    "LyricsCacheHit",
    "LyricsCacheKey",
    "LyricsCacheMode",
    "LyricsCacheQuery",
    "cache_path",
]
