import sqlite3
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from kotonoha.app.track_offset_service import TrackOffsetPersistenceState, TrackOffsetService
from kotonoha.display.offsets import TrackOffsetEntry, TrackOffsetKey, TrackOffsetSnapshot, track_offset_key
from kotonoha.lyrics.models import LyricLine, LyricsCacheState, LyricsDocument, LyricsOrigin, TimingKind
from kotonoha.playback.models import TrackIdentity
from kotonoha.state import TrackOffsetStore


def _track() -> TrackIdentity:
    return TrackIdentity(
        "test",
        "player",
        stable_id="recording",
        title="Song",
        artist="Artist",
        album="Album",
        duration_s=180.0,
    )


def _document(line_text: str, *, source_id: str = "netease", song_id: str | None = "song-1") -> LyricsDocument:
    return LyricsDocument(
        source_id,
        song_id=song_id,
        timing=TimingKind.LINE,
        title="Song",
        artist="Artist",
        album="Album",
        duration_s=180.0,
        lines=(LyricLine(0, "line-0", 0.0, 3.0, line_text, ""),),
    )


def _key(document: LyricsDocument) -> TrackOffsetKey:
    key = track_offset_key(_track(), document)
    assert key is not None
    return key


def test_offset_identity_changes_with_lyrics_but_not_cache_or_manual_state() -> None:
    automatic = _document("original")
    manual = replace(automatic, origin=LyricsOrigin.MANUAL, cache_state=LyricsCacheState.MANUAL)
    changed = _document("replacement")
    other_source = _document("original", source_id="lrclib", song_id="other")
    near_duration = track_offset_key(replace(_track(), duration_s=180.001), automatic)

    assert _key(automatic) == _key(manual)
    assert _key(automatic) != _key(changed)
    assert _key(automatic) != _key(other_source)
    assert near_duration == _key(automatic)
    assert _key(automatic).track_duration_s == 180


def test_sqlite_roundtrip_keeps_many_lyric_versions_without_an_entry_cap(tmp_path: Path) -> None:
    store = TrackOffsetStore(tmp_path / "track-offsets.sqlite3")
    keys = tuple(_key(_document(f"line-{index}")) for index in range(101))
    snapshot = TrackOffsetSnapshot(tuple(TrackOffsetEntry(key, index) for index, key in enumerate(keys)))

    for entry in snapshot.entries:
        store.upsert(entry)
    loaded = store.load()

    assert len(loaded.entries) == 101
    assert loaded.offset_for(keys[0]) == 0
    assert loaded.offset_for(keys[-1]) == 100


def test_sqlite_store_uses_a_structured_primary_key(tmp_path: Path) -> None:
    path = tmp_path / "track-offsets.sqlite3"
    key = _key(_document("line"))
    replacement = TrackOffsetEntry(key, 300)
    other = TrackOffsetEntry(_key(_document("other")), -125)
    store = TrackOffsetStore(path)
    store.upsert(TrackOffsetEntry(key, 250))
    store.upsert(other)
    store.upsert(replacement)

    loaded = store.load()
    assert loaded.offset_for(key) == 300
    assert loaded.offset_for(other.key) == -125

    with sqlite3.connect(path) as connection:
        columns = tuple(row[1] for row in connection.execute("PRAGMA table_info(track_offsets)"))
        primary_key_columns = tuple(
            row[1]
            for row in sorted(connection.execute("PRAGMA table_info(track_offsets)"), key=lambda row: row[5])
            if row[5]
        )

    assert "lyrics_digest" in columns
    assert primary_key_columns == (
        "track_title",
        "track_artist",
        "track_album",
        "track_duration_s",
        "lyrics_source_id",
        "lyrics_song_id",
        "lyrics_digest",
    )


def test_sqlite_store_migrates_legacy_millisecond_duration(tmp_path: Path) -> None:
    path = tmp_path / "track-offsets.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE track_offsets (
                track_title TEXT NOT NULL,
                track_artist TEXT NOT NULL,
                track_album TEXT NOT NULL,
                track_duration_ms INTEGER NOT NULL,
                lyrics_source_id TEXT NOT NULL,
                lyrics_song_id TEXT NOT NULL,
                lyrics_digest TEXT NOT NULL,
                offset_ms INTEGER NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (
                    track_title, track_artist, track_album, track_duration_ms,
                    lyrics_source_id, lyrics_song_id, lyrics_digest
                )
            ) WITHOUT ROWID;
            PRAGMA user_version = 1;
            """
        )
        connection.execute(
            "INSERT INTO track_offsets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("song", "artist", "album", 180001, "test", "song-1", "a" * 64, 250, 1.0),
        )

    store = TrackOffsetStore(path)
    key = TrackOffsetKey("song", "artist", "album", 180, "test", "song-1", "a" * 64)

    assert store.load().offset_for(key) == 250
    with sqlite3.connect(path) as connection:
        columns = tuple(row[1] for row in connection.execute("PRAGMA table_info(track_offsets)"))
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert "track_duration_s" in columns
    assert "track_duration_ms" not in columns
    assert version == 2


class _MemoryOffsetWriter:
    def __init__(self) -> None:
        self.saved: list[TrackOffsetEntry] = []

    def upsert(self, entry: TrackOffsetEntry) -> None:
        self.saved.append(entry)


class _FailingOffsetWriter(_MemoryOffsetWriter):
    def __init__(self) -> None:
        super().__init__()
        self.failures = 1

    def upsert(self, entry: TrackOffsetEntry) -> None:
        if self.failures > 0:
            self.failures -= 1
            raise OSError("test write failed")
        super().upsert(entry)


class _ImmediateWorker:
    async def run(
        self,
        function: Callable[..., object],
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        return function(*args, **kwargs)

    def close(self) -> None:
        return None

    def reopen(self) -> None:
        return None


@pytest.mark.asyncio
async def test_service_applies_offset_immediately_and_persists_latest_entries() -> None:
    key = _key(_document("line"))
    other_key = _key(_document("other line"))
    writer = _MemoryOffsetWriter()
    service = TrackOffsetService(
        TrackOffsetSnapshot(),
        writer=writer,
        worker=_ImmediateWorker(),
    )

    service.set_offset(key, 125)
    service.set_offset(other_key, -75)
    assert service.offset_for(key) == 125
    assert service.offset_for(other_key) == -75
    assert service.persistence_status.state is TrackOffsetPersistenceState.PENDING

    await service.flush()

    assert service.persistence_status.state is TrackOffsetPersistenceState.IDLE
    assert {entry.key: entry.offset_ms for entry in writer.saved} == {key: 125, other_key: -75}
    await service.close()


@pytest.mark.asyncio
async def test_service_reports_persistence_failure_and_retries_pending_entry() -> None:
    key = _key(_document("line"))
    writer = _FailingOffsetWriter()
    service = TrackOffsetService(
        TrackOffsetSnapshot(),
        writer=writer,
        worker=_ImmediateWorker(),
    )

    service.set_offset(key, 125)
    await service.flush()

    assert service.persistence_status.state is TrackOffsetPersistenceState.FAILED
    assert service.persistence_status.error == "test write failed"
    assert writer.saved == []

    service.retry_persistence()
    await service.flush()

    assert service.persistence_status.state is TrackOffsetPersistenceState.IDLE
    assert writer.saved[-1] == TrackOffsetEntry(key, 125)
    await service.close()
