"""Provider-scoped persistent cache for validated lyric artifacts."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

from ...async_worker import BlockingWorkerPort
from ..artifact import LyricsArtifact
from ..match import Candidate, MatchConfidence, MatchEvidence, TrackMetadata, evaluate_match
from ..models import LyricLine
from ..title_grammar import NORMALIZER_VERSION
from .models import (
    CacheDeleteResult,
    CacheDeleteStatus,
    CacheWriteResult,
    CacheWriteStatus,
    LyricsCacheEntry,
    LyricsCacheKey,
    LyricsCacheMode,
    LyricsCacheQuery,
)

CACHE_SCHEMA_VERSION = 1
DEFAULT_MAX_ENTRIES = 1000
_CACHE_SEARCH_FIELDS: Final[tuple[str, ...]] = ("title", "artist", "album", "provider", "provider_song_id")

PayloadParser = Callable[[Mapping[str, str]], tuple[LyricLine, ...]]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lyrics (
    provider TEXT NOT NULL,
    provider_song_id TEXT NOT NULL,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,
    album TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'auto',
    duration_s REAL,
    payload_json TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    last_accessed REAL NOT NULL,
    schema_version INTEGER NOT NULL,
    normalizer_version INTEGER NOT NULL,
    PRIMARY KEY (provider, provider_song_id)
);
CREATE INDEX IF NOT EXISTS lyrics_provider_access
    ON lyrics(provider, last_accessed DESC);
"""


class LyricsCacheError(RuntimeError):
    """A cache operation failed behind the persistent-storage boundary."""


def cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "kotonoha" / "lyrics.sqlite3"


class LyricsCache:
    def __init__(
        self,
        path: Path | None = None,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        worker: BlockingWorkerPort,
    ) -> None:
        self._path = path or cache_path()
        self._max_entries = max(1, max_entries)
        self._worker = worker

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
    ) -> LyricsArtifact | None:
        try:
            return await self._worker.run(self._lookup_sync, provider, track, parser)
        except (OSError, sqlite3.Error) as exc:
            raise LyricsCacheError("Lyrics cache lookup failed") from exc

    async def store(self, artifact: LyricsArtifact) -> CacheWriteResult | None:
        """Persist an automatically resolved artifact only at high confidence."""
        if artifact.confidence is MatchConfidence.HIGH:
            return await self.upsert(artifact, mode=LyricsCacheMode.AUTO)
        return None

    async def search(self, query: LyricsCacheQuery) -> tuple[LyricsCacheEntry, ...]:
        """Return matching cache metadata in deterministic recent-use order."""
        try:
            return await self._worker.run(self._search_sync, query)
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            raise LyricsCacheError("Lyrics cache search failed") from exc

    async def get(self, key: LyricsCacheKey) -> LyricsCacheEntry | None:
        """Return one cache entry by its provider-scoped key."""
        try:
            return await self._worker.run(self._get_sync, key)
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            raise LyricsCacheError("Lyrics cache read failed") from exc

    async def upsert(
        self,
        artifact: LyricsArtifact,
        *,
        mode: LyricsCacheMode = LyricsCacheMode.MANUAL,
    ) -> CacheWriteResult:
        """Create or replace a validated artifact for an explicit application workflow.

        Unlike :meth:`store`, this method does not apply the automatic confidence gate.
        A future user-selection workflow may call it after the user explicitly confirms
        a provider result. Explicit writes default to ``MANUAL``.
        """
        _validate_artifact(artifact)
        _validate_mode(mode)
        try:
            return await self._worker.run(self._upsert_sync, artifact, mode)
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
            return await self._worker.run(self._update_sync, key, artifact, mode)
        except (OSError, sqlite3.Error) as exc:
            raise LyricsCacheError("Lyrics cache update failed") from exc

    async def delete(self, key: LyricsCacheKey) -> CacheDeleteResult:
        """Delete one entry and report when it was already absent."""
        try:
            return await self._worker.run(self._delete_sync, key)
        except (OSError, sqlite3.Error) as exc:
            raise LyricsCacheError("Lyrics cache delete failed") from exc

    async def delete_many(self, keys: tuple[LyricsCacheKey, ...]) -> tuple[CacheDeleteResult, ...]:
        """Delete several exact entries in one owned SQLite operation."""
        try:
            return await self._worker.run(self._delete_many_sync, keys)
        except (OSError, sqlite3.Error) as exc:
            raise LyricsCacheError("Lyrics cache delete failed") from exc

    async def clear(self) -> None:
        try:
            await self._worker.run(self._clear_sync)
        except (OSError, sqlite3.Error) as exc:
            raise LyricsCacheError("Lyrics cache clear failed") from exc

    async def count(self) -> int:
        try:
            return await self._worker.run(self._count_sync)
        except (OSError, sqlite3.Error) as exc:
            raise LyricsCacheError("Lyrics cache count failed") from exc

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, timeout=3.0)
        connection.row_factory = sqlite3.Row
        connection.executescript(_SCHEMA)
        self._ensure_mode_column(connection)
        return connection

    @staticmethod
    def _ensure_mode_column(connection: sqlite3.Connection) -> None:
        """Add metadata introduced after the first cache schema without losing rows."""
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(lyrics)")}
        if "mode" not in columns:
            connection.execute("ALTER TABLE lyrics ADD COLUMN mode TEXT NOT NULL DEFAULT 'auto'")

    def _lookup_sync(
        self,
        provider: str,
        track: TrackMetadata,
        parser: PayloadParser,
    ) -> LyricsArtifact | None:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM lyrics "
                "WHERE provider = ? AND schema_version = ? AND normalizer_version = ?",
                (provider, CACHE_SCHEMA_VERSION, NORMALIZER_VERSION),
            ).fetchall()
            matches: list[tuple[MatchEvidence, sqlite3.Row]] = []
            for row in rows:
                candidate = Candidate(
                    song_id=row["provider_song_id"],
                    title=row["title"],
                    artist=row["artist"],
                    duration_s=row["duration_s"],
                    album=row["album"],
                )
                evidence = evaluate_match(candidate, track)
                if evidence.confidence is MatchConfidence.HIGH:
                    matches.append((evidence, row))
            if not matches:
                return None

            evidence, row = max(matches, key=lambda item: self._match_sort_key(item[0]))
            try:
                raw_payload = json.loads(row["payload_json"])
                if not isinstance(raw_payload, dict) or not all(
                    isinstance(key, str) and isinstance(value, str) for key, value in raw_payload.items()
                ):
                    raise TypeError("cached payload is not a string map")
                payload: dict[str, str] = raw_payload
                lines = parser(payload)
                if not lines:
                    raise ValueError("cached payload has no timed lyrics")
            except (json.JSONDecodeError, TypeError, ValueError):
                connection.execute(
                    "DELETE FROM lyrics WHERE provider = ? AND provider_song_id = ?",
                    (provider, row["provider_song_id"]),
                )
                return None

            connection.execute(
                "UPDATE lyrics SET last_accessed = ? WHERE provider = ? AND provider_song_id = ?",
                (time.time(), provider, row["provider_song_id"]),
            )
            return LyricsArtifact(
                provider=provider,
                provider_song_id=row["provider_song_id"],
                title=row["title"],
                artist=row["artist"],
                album=row["album"],
                duration_s=row["duration_s"],
                payload=payload,
                lines=lines,
                confidence=evidence.confidence,
            )

    @staticmethod
    def _match_sort_key(evidence: MatchEvidence) -> tuple[bool, bool, bool, float]:
        duration_rank = -evidence.duration_delta if evidence.duration_delta is not None else float("-inf")
        return evidence.title_exact, evidence.artist_overlap, evidence.album_match, duration_rank

    def _search_sync(self, query: LyricsCacheQuery) -> tuple[LyricsCacheEntry, ...]:
        keyword = query.keyword.strip().casefold()
        with self._connect() as connection:
            if query.provider is None:
                rows = connection.execute(
                    "SELECT provider, provider_song_id, title, artist, album, mode, duration_s, fetched_at, "
                    "last_accessed "
                    "FROM lyrics ORDER BY last_accessed DESC, provider ASC, provider_song_id ASC"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT provider, provider_song_id, title, artist, album, mode, duration_s, fetched_at, "
                    "last_accessed "
                    "FROM lyrics WHERE provider = ? "
                    "ORDER BY last_accessed DESC, provider ASC, provider_song_id ASC",
                    (query.provider,),
                ).fetchall()
        entries = tuple(self._entry_from_row(row) for row in rows)
        if not keyword:
            return entries
        return tuple(entry for entry in entries if _entry_matches(entry, keyword))

    def _get_sync(self, key: LyricsCacheKey) -> LyricsCacheEntry | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT provider, provider_song_id, title, artist, album, mode, duration_s, fetched_at, last_accessed "
                "FROM lyrics WHERE provider = ? AND provider_song_id = ?",
                (key.provider, key.provider_song_id),
            ).fetchone()
        return None if row is None else self._entry_from_row(row)

    def _upsert_sync(self, artifact: LyricsArtifact, mode: LyricsCacheMode) -> CacheWriteResult:
        now = time.time()
        payload_json = json.dumps(artifact.payload, ensure_ascii=False, separators=(",", ":"))
        key = LyricsCacheKey(artifact.provider, artifact.provider_song_id)
        with self._connect() as connection:
            existed = connection.execute(
                "SELECT 1 FROM lyrics WHERE provider = ? AND provider_song_id = ?",
                (key.provider, key.provider_song_id),
            ).fetchone() is not None
            connection.execute(
                "INSERT INTO lyrics ("
                "provider, provider_song_id, title, artist, album, mode, duration_s, payload_json, "
                "fetched_at, last_accessed, schema_version, normalizer_version"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(provider, provider_song_id) DO UPDATE SET "
                "title = excluded.title, artist = excluded.artist, album = excluded.album, mode = excluded.mode, "
                "duration_s = excluded.duration_s, payload_json = excluded.payload_json, "
                "fetched_at = excluded.fetched_at, last_accessed = excluded.last_accessed, "
                "schema_version = excluded.schema_version, normalizer_version = excluded.normalizer_version",
                (
                    artifact.provider,
                    artifact.provider_song_id,
                    artifact.title,
                    artifact.artist,
                    artifact.album,
                    mode.value,
                    artifact.duration_s,
                    payload_json,
                    now,
                    now,
                    CACHE_SCHEMA_VERSION,
                    NORMALIZER_VERSION,
                ),
            )
            connection.execute(
                "DELETE FROM lyrics WHERE rowid IN ("
                "SELECT rowid FROM lyrics ORDER BY last_accessed DESC LIMIT -1 OFFSET ?)",
                (self._max_entries,),
            )
        status = CacheWriteStatus.UPDATED if existed else CacheWriteStatus.CREATED
        return CacheWriteResult(key, status)

    def _update_sync(self, key: LyricsCacheKey, artifact: LyricsArtifact, mode: LyricsCacheMode) -> CacheWriteResult:
        now = time.time()
        payload_json = json.dumps(artifact.payload, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE lyrics SET title = ?, artist = ?, album = ?, mode = ?, duration_s = ?, payload_json = ?, "
                "fetched_at = ?, last_accessed = ?, schema_version = ?, normalizer_version = ? "
                "WHERE provider = ? AND provider_song_id = ?",
                (
                    artifact.title,
                    artifact.artist,
                    artifact.album,
                    mode.value,
                    artifact.duration_s,
                    payload_json,
                    now,
                    now,
                    CACHE_SCHEMA_VERSION,
                    NORMALIZER_VERSION,
                    key.provider,
                    key.provider_song_id,
                ),
            )
        status = CacheWriteStatus.UPDATED if cursor.rowcount else CacheWriteStatus.NOT_FOUND
        return CacheWriteResult(key, status)

    def _delete_sync(self, key: LyricsCacheKey) -> CacheDeleteResult:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM lyrics WHERE provider = ? AND provider_song_id = ?",
                (key.provider, key.provider_song_id),
            )
        status = CacheDeleteStatus.DELETED if cursor.rowcount else CacheDeleteStatus.NOT_FOUND
        return CacheDeleteResult(key, status)

    def _delete_many_sync(self, keys: tuple[LyricsCacheKey, ...]) -> tuple[CacheDeleteResult, ...]:
        with self._connect() as connection:
            results: list[CacheDeleteResult] = []
            for key in keys:
                cursor = connection.execute(
                    "DELETE FROM lyrics WHERE provider = ? AND provider_song_id = ?",
                    (key.provider, key.provider_song_id),
                )
                status = CacheDeleteStatus.DELETED if cursor.rowcount else CacheDeleteStatus.NOT_FOUND
                results.append(CacheDeleteResult(key, status))
        return tuple(results)

    @staticmethod
    def _entry_from_row(row: sqlite3.Row) -> LyricsCacheEntry:
        provider = row["provider"]
        provider_song_id = row["provider_song_id"]
        title = row["title"]
        artist = row["artist"]
        album = row["album"]
        raw_mode = row["mode"]
        duration = row["duration_s"]
        fetched_at = row["fetched_at"]
        last_accessed = row["last_accessed"]
        if not all(isinstance(value, str) for value in (provider, provider_song_id, title, artist, album, raw_mode)):
            raise TypeError("cache metadata contains a non-string value")
        try:
            mode = LyricsCacheMode(raw_mode)
        except ValueError as exc:
            raise ValueError("cache mode is invalid") from exc
        if duration is not None and (not isinstance(duration, (int, float)) or isinstance(duration, bool)):
            raise TypeError("cache duration is not numeric")
        if not isinstance(fetched_at, (int, float)) or isinstance(fetched_at, bool):
            raise TypeError("cache fetch time is not numeric")
        if not isinstance(last_accessed, (int, float)) or isinstance(last_accessed, bool):
            raise TypeError("cache access time is not numeric")
        return LyricsCacheEntry(
            key=LyricsCacheKey(provider, provider_song_id),
            title=title,
            artist=artist,
            album=album,
            duration_s=float(duration) if duration is not None else None,
            fetched_at=float(fetched_at),
            last_accessed=float(last_accessed),
            mode=mode,
        )

    def _clear_sync(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM lyrics")

    def _count_sync(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM lyrics").fetchone()
        return int(row["count"]) if row is not None else 0


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


def _entry_matches(entry: LyricsCacheEntry, keyword: str) -> bool:
    """Match a case-folded keyword against all searchable cache metadata."""
    values = {
        "title": entry.title,
        "artist": entry.artist,
        "album": entry.album,
        "provider": entry.key.provider,
        "provider_song_id": entry.key.provider_song_id,
    }
    return any(keyword in values[field].casefold() for field in _CACHE_SEARCH_FIELDS)


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
    "LyricsCacheKey",
    "LyricsCacheMode",
    "LyricsCacheQuery",
    "cache_path",
]
