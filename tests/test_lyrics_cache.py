import sqlite3

import pytest

from kotonoha.async_worker import BlockingCallRunner
from kotonoha.lyrics import netease
from kotonoha.lyrics.artifact import LyricsArtifact
from kotonoha.lyrics.cache import (
    CacheDeleteStatus,
    CacheWriteStatus,
    LyricsCache,
    LyricsCacheError,
    LyricsCacheHit,
    LyricsCacheKey,
    LyricsCacheMode,
    LyricsCacheQuery,
)
from kotonoha.lyrics.match import MatchConfidence, TrackMetadata
from kotonoha.lyrics.models import LyricLine


def cache_for(path=None, *, max_entries=1000):
    """Build a cache with an explicitly owned test worker."""
    return LyricsCache(
        path,
        max_entries=max_entries,
        worker=BlockingCallRunner("test-lyrics-cache"),
    )


def artifact(
    *,
    provider: str = "netease",
    provider_song_id: str = "1",
    title: str = "Song",
    artist: str = "Artist",
    album: str = "Album",
    confidence: MatchConfidence = MatchConfidence.HIGH,
) -> LyricsArtifact:
    payload = (
        {"lrc": "[00:01.00]line", "yrc": "", "tlyric": ""}
        if provider == "netease"
        else {"syncedLyrics": "[00:01.00]line"}
    )
    return LyricsArtifact(
        provider=provider,
        provider_song_id=provider_song_id,
        title=title,
        artist=artist,
        album=album,
        duration_s=180.0,
        payload=payload,
        lines=(LyricLine(0, "L0", 1.0, 6.0, "line", ""),),
        confidence=confidence,
    )


async def test_lookup_is_scoped_to_provider_and_matches_metadata(tmp_path):
    cache = cache_for(tmp_path / "lyrics.sqlite3", max_entries=10)
    await cache.store(artifact(provider="netease", provider_song_id="1"))
    await cache.store(artifact(provider="lrclib", provider_song_id="2"))

    track = TrackMetadata("Ｓｏｎｇ", "Artist", "Album", 180.0)
    hit = await cache.lookup("netease", track, netease.parse_payload)

    assert hit is not None
    assert hit.mode is LyricsCacheMode.AUTO
    assert hit.artifact.provider == "netease"
    assert hit.artifact.provider_song_id == "1"


async def test_lookup_does_not_require_player_track_or_search_key(tmp_path):
    path = tmp_path / "lyrics.sqlite3"
    cache = cache_for(path)
    await cache.store(artifact())

    hit = await cache.lookup("netease", TrackMetadata("Song", "Artist", "", 180.0), netease.parse_payload)
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(lyrics)")}

    assert hit is not None
    assert hit.mode is LyricsCacheMode.AUTO
    assert not columns & {"player", "track_id", "search_key", "query", "alias"}


async def test_only_high_confidence_artifacts_are_persisted(tmp_path):
    cache = cache_for(tmp_path / "lyrics.sqlite3")
    await cache.store(artifact(confidence=MatchConfidence.MEDIUM))
    assert await cache.count() == 0


async def test_search_returns_multiple_fuzzy_matches_and_supports_provider_filter(tmp_path):
    cache = cache_for(tmp_path / "lyrics.sqlite3")
    await cache.store(artifact(provider="netease", provider_song_id="1", title="Morning Song"))
    await cache.store(artifact(provider="lrclib", provider_song_id="2", title="Song at Night"))
    await cache.store(artifact(provider="qqmusic", provider_song_id="3", title="Instrumental"))

    matches = await cache.search(LyricsCacheQuery(keyword="song"))
    filtered = await cache.search(LyricsCacheQuery(keyword="song", provider="lrclib"))

    assert {entry.key for entry in matches} == {
        LyricsCacheKey("netease", "1"),
        LyricsCacheKey("lrclib", "2"),
    }
    assert [entry.key for entry in filtered] == [LyricsCacheKey("lrclib", "2")]


async def test_explicit_upsert_and_update_report_identity_and_delete_outcomes(tmp_path):
    cache = cache_for(tmp_path / "lyrics.sqlite3")
    selected = artifact(provider="netease", provider_song_id="selected", confidence=MatchConfidence.MEDIUM)

    created = await cache.upsert(selected)
    updated = await cache.update(
        created.key,
        artifact(
            provider="netease",
            provider_song_id="selected",
            title="Updated song",
            confidence=MatchConfidence.MEDIUM,
        ),
    )
    missing = await cache.update(
        LyricsCacheKey("netease", "missing"),
        artifact(provider="netease", provider_song_id="missing", confidence=MatchConfidence.MEDIUM),
    )
    deleted = await cache.delete_many((created.key, missing.key))

    assert created.status is CacheWriteStatus.CREATED
    assert updated.status is CacheWriteStatus.UPDATED
    assert missing.status is CacheWriteStatus.NOT_FOUND
    assert [result.status for result in deleted] == [CacheDeleteStatus.DELETED, CacheDeleteStatus.NOT_FOUND]
    assert await cache.get(created.key) is None


async def test_automatic_and_explicit_writes_record_the_selection_mode(tmp_path):
    cache = cache_for(tmp_path / "lyrics.sqlite3")
    await cache.store(artifact(provider_song_id="automatic"))
    await cache.upsert(artifact(provider_song_id="manual"))
    await cache.update(
        LyricsCacheKey("netease", "manual"),
        artifact(provider_song_id="manual", title="Updated manually"),
        mode=LyricsCacheMode.AUTO,
    )

    automatic = await cache.get(LyricsCacheKey("netease", "automatic"))
    manual = await cache.get(LyricsCacheKey("netease", "manual"))

    assert automatic is not None and automatic.mode is LyricsCacheMode.AUTO
    assert manual is not None and manual.title == "Updated manually"
    assert manual.mode is LyricsCacheMode.AUTO


async def test_manual_lookup_returns_the_latest_matching_selection_across_providers(tmp_path):
    from kotonoha.lyrics import lrclib

    cache = cache_for(tmp_path / "lyrics.sqlite3")
    await cache.store(artifact(provider="netease", provider_song_id="automatic"))
    await cache.upsert(artifact(provider="lrclib", provider_song_id="manual"))

    hit = await cache.lookup_manual(
        TrackMetadata("Song", "Artist", "Album", 180.0),
        {"netease": netease.parse_payload, "lrclib": lrclib.parse_payload},
    )

    assert isinstance(hit, LyricsCacheHit)
    assert hit.mode is LyricsCacheMode.MANUAL
    assert hit.artifact.provider == "lrclib"

    deleted = await cache.delete(LyricsCacheKey("lrclib", "manual"))
    automatic = await cache.lookup(
        "netease",
        TrackMetadata("Song", "Artist", "Album", 180.0),
        netease.parse_payload,
    )

    assert deleted.status is CacheDeleteStatus.DELETED
    assert await cache.lookup_manual(
        TrackMetadata("Song", "Artist", "Album", 180.0),
        {"netease": netease.parse_payload, "lrclib": lrclib.parse_payload},
    ) is None
    assert automatic is not None and automatic.mode is LyricsCacheMode.AUTO


async def test_legacy_rows_receive_auto_mode_during_schema_migration(tmp_path):
    path = tmp_path / "lyrics.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE lyrics (
                provider TEXT NOT NULL,
                provider_song_id TEXT NOT NULL,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                album TEXT NOT NULL,
                duration_s REAL,
                payload_json TEXT NOT NULL,
                fetched_at REAL NOT NULL,
                last_accessed REAL NOT NULL,
                schema_version INTEGER NOT NULL,
                normalizer_version INTEGER NOT NULL,
                PRIMARY KEY (provider, provider_song_id)
            );
            """
        )
        connection.execute(
            "INSERT INTO lyrics VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("netease", "legacy", "Song", "Artist", "Album", 180.0, "{}", 1.0, 2.0, 1, 1),
        )

    cache = cache_for(path)
    entry = await cache.get(LyricsCacheKey("netease", "legacy"))

    assert entry is not None
    assert entry.mode is LyricsCacheMode.AUTO
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(lyrics)")}
    assert "mode" in columns


async def test_invalid_payload_is_removed(tmp_path):
    path = tmp_path / "lyrics.sqlite3"
    cache = cache_for(path)
    await cache.store(artifact())
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE lyrics SET payload_json = ?", ("not json",))

    hit = await cache.lookup("netease", TrackMetadata("Song", "Artist", "Album", 180.0), netease.parse_payload)

    assert hit is None
    assert await cache.count() == 0


async def test_clear_and_lru_pruning(tmp_path):
    cache = cache_for(tmp_path / "lyrics.sqlite3", max_entries=2)
    await cache.store(artifact(provider_song_id="1"))
    await cache.store(artifact(provider_song_id="2"))
    await cache.store(artifact(provider_song_id="3"))
    assert await cache.count() == 2
    await cache.clear()
    assert await cache.count() == 0


async def test_storage_failures_are_normalized_at_the_cache_boundary(tmp_path):
    path = tmp_path / "cache-directory"
    path.mkdir()
    cache = cache_for(path)
    try:
        with pytest.raises(LyricsCacheError):
            await cache.lookup("netease", TrackMetadata("Song", "Artist"), netease.parse_payload)
    finally:
        cache.close()
