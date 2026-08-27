"""MPRIS player facade backed by dedicated playback and lyric coordinators."""

from __future__ import annotations

import logging

from ..config import DEFAULT_LYRICS_SOURCES
from ..display.coordinator import DisplayCoordinator
from ..lyrics.ownership import SourceOwnershipCoordinator
from ..lyrics.workflow import ResolverPort
from ..players import PlayerInfo
from .mpris_adapter import MprisPlaybackAdapter
from .mpris_lyrics import MprisLyricsCoordinator
from .mpris_playback import MprisPlaybackCoordinator, PlaybackSample
from .mpris_track import TrackCommit

logger = logging.getLogger(__name__)


class MprisProvider:
    """Compose MPRIS polling with the application-owned lyric workflow."""

    def __init__(
        self,
        display: DisplayCoordinator,
        poll_interval: float = 0.2,
        *,
        lyrics_sources: list[str] | None = None,
        ownership: SourceOwnershipCoordinator,
        resolver: ResolverPort,
        playback_adapter: MprisPlaybackAdapter | None = None,
    ) -> None:
        """Create the MPRIS facade from the composition root's dependencies."""
        self._ownership = ownership
        self._resolver: ResolverPort = resolver
        self._playback_adapter = playback_adapter if playback_adapter is not None else MprisPlaybackAdapter()
        self._lyrics = MprisLyricsCoordinator(
            display,
            ownership=self._ownership,
            resolver=self._resolver,
            playback_adapter=self._playback_adapter,
            lyrics_sources=lyrics_sources if lyrics_sources is not None else list(DEFAULT_LYRICS_SOURCES),
        )
        self._playback = MprisPlaybackCoordinator(
            poll_interval=poll_interval,
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

    async def start(self) -> None:
        """Start MPRIS polling and lyric HTTP resources."""
        await self._playback.start()
        await self._lyrics.start()
        logger.info("MPRIS provider started")

    async def stop(self) -> None:
        """Stop polling before closing lyric workflow resources."""
        await self._playback.stop()
        await self._lyrics.stop()

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
