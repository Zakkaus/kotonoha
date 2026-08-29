"""MPRIS player facade backed by dedicated playback and lyric coordinators."""

from __future__ import annotations

import asyncio
import logging

from ..app.source_contracts import MprisSourcePort
from ..config import DEFAULT_LYRICS_SOURCES
from ..display.contracts import MprisDisplayPort
from ..lyrics.artifact import LyricsArtifact
from ..lyrics.cache import (
    CacheDeleteResult,
    CacheWriteResult,
    LyricsCacheEntry,
    LyricsCacheKey,
    LyricsCacheMode,
    LyricsCacheQuery,
)
from ..lyrics.workflow import ResolverPort
from ..players import PlayerInfo
from .mpris_adapter import MprisPlaybackAdapter
from .mpris_lyrics import MprisLyricsCoordinator
from .mpris_playback import MprisPlaybackCoordinator, MprisSessionPort, PlaybackSample
from .mpris_track import TrackCommit

logger = logging.getLogger(__name__)


class MprisProvider:
    """Compose MPRIS polling with the application-owned lyric workflow."""

    def __init__(
        self,
        display: MprisDisplayPort,
        poll_interval: float = 0.2,
        *,
        lyrics_sources: list[str] | None = None,
        ownership: MprisSourcePort,
        resolver: ResolverPort,
        playback_adapter: MprisPlaybackAdapter,
        playback_session: MprisSessionPort,
    ) -> None:
        """Create the MPRIS facade from the composition root's dependencies."""
        self._ownership = ownership
        self._resolver: ResolverPort = resolver
        self._playback_adapter = playback_adapter
        self._lyrics = MprisLyricsCoordinator(
            display,
            ownership=self._ownership,
            resolver=self._resolver,
            playback_adapter=self._playback_adapter,
            lyrics_sources=lyrics_sources if lyrics_sources is not None else list(DEFAULT_LYRICS_SOURCES),
        )
        self._playback = MprisPlaybackCoordinator(
            poll_interval=poll_interval,
            session=playback_session,
            playback_adapter=self._playback_adapter,
            on_sample=self._on_playback_sample,
            on_commit=self._on_playback_commit,
            on_no_player=self._handle_no_player,
        )
        self._cache_enabled = True
        self._prefer_best = True
        self._fuzzy = True

    def set_lyrics_sources(self, sources: list[str]) -> None:
        """Replace the ordered source plan used for future tracks."""
        self._lyrics.set_lyrics_sources(sources)

    def set_player_lock(self, bus_name: str) -> None:
        """Select the MPRIS bus name owned by the playback coordinator."""
        self._playback.set_player_lock(bus_name)

    async def available_players(self) -> list[PlayerInfo]:
        """Return the player list collected through the playback coordinator."""
        return await self._playback.available_players()

    def set_cache_enabled(self, enabled: bool) -> None:
        """Toggle persistent lyric caching and reload the current track."""
        updated = bool(enabled)
        if updated == self._cache_enabled:
            return
        self._cache_enabled = updated
        self._lyrics.set_cache_enabled(updated)

    def set_prefer_best(self, enabled: bool) -> None:
        """Toggle best-result arbitration and reload the current track."""
        updated = bool(enabled)
        if updated == self._prefer_best:
            return
        self._prefer_best = updated
        self._lyrics.set_prefer_best(updated)

    def set_fuzzy(self, enabled: bool) -> None:
        """Toggle fuzzy matching and reload the current track."""
        updated = bool(enabled)
        if updated == self._fuzzy:
            return
        self._fuzzy = updated
        self._lyrics.set_fuzzy(updated)

    async def clear_cache(self) -> None:
        """Clear the resolver's persistent cache."""
        await self._lyrics.clear_cache()

    async def search_cache(self, query: LyricsCacheQuery) -> tuple[LyricsCacheEntry, ...]:
        """Search persisted lyric cache metadata."""
        return await self._lyrics.search_cache(query)

    async def get_cache(self, key: LyricsCacheKey) -> LyricsCacheEntry | None:
        """Read one persisted lyric cache entry."""
        return await self._lyrics.get_cache(key)

    async def upsert_cache(
        self,
        artifact: LyricsArtifact,
        *,
        mode: LyricsCacheMode = LyricsCacheMode.MANUAL,
    ) -> CacheWriteResult:
        """Persist a validated result selected by an explicit lyric workflow."""
        return await self._lyrics.upsert_cache(artifact, mode=mode)

    async def update_cache(
        self,
        key: LyricsCacheKey,
        artifact: LyricsArtifact,
        *,
        mode: LyricsCacheMode = LyricsCacheMode.MANUAL,
    ) -> CacheWriteResult:
        """Update one existing persisted lyric cache entry and record its mode."""
        return await self._lyrics.update_cache(key, artifact, mode=mode)

    async def delete_cache(self, key: LyricsCacheKey) -> CacheDeleteResult:
        """Delete one persisted lyric cache entry."""
        return await self._lyrics.delete_cache(key)

    async def delete_cache_many(self, keys: tuple[LyricsCacheKey, ...]) -> tuple[CacheDeleteResult, ...]:
        """Delete several persisted lyric cache entries."""
        return await self._lyrics.delete_cache_many(keys)

    async def start(self) -> None:
        """Start MPRIS polling and lyric HTTP resources."""
        await self._playback.start()
        lyrics_started = False
        try:
            await self._lyrics.start()
            lyrics_started = True
        finally:
            if not lyrics_started:
                await self._rollback_playback_start()
        logger.info("MPRIS provider started")

    async def stop(self) -> None:
        """Stop polling before closing lyric workflow resources."""
        first_error: Exception | None = None
        cancelled = False
        try:
            await self._playback.stop()
        except asyncio.CancelledError:
            cancelled = True
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            logger.warning("Could not stop MPRIS playback coordinator: %s", exc)
            first_error = exc
        finally:
            try:
                await self._lyrics.stop()
            except asyncio.CancelledError:
                cancelled = True
            except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
                logger.warning("Could not stop MPRIS lyrics coordinator: %s", exc)
                if first_error is None:
                    first_error = exc
        if cancelled:
            raise asyncio.CancelledError
        if first_error is not None:
            raise first_error

    async def _rollback_playback_start(self) -> None:
        """Release playback resources when lyric startup fails halfway through."""
        try:
            await self._playback.stop()
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            logger.warning("Could not roll back MPRIS playback startup: %s", exc)

    def _on_playback_commit(self, commit: TrackCommit) -> None:
        """Forward stable playback transitions to the lyric coordinator."""
        self._lyrics.on_playback_commit(commit)

    def _on_playback_sample(self, sample: PlaybackSample) -> None:
        """Forward normalized playback samples to the lyric coordinator."""
        self._lyrics.on_playback_sample(sample)

    def _handle_no_player(self, now: float) -> None:
        """Reset both playback stabilization and lyrics after a sustained absence."""
        if self._lyrics.handle_no_player(now):
            self._playback.reset()


__all__ = ["MprisProvider"]
