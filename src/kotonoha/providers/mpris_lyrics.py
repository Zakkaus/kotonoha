"""MPRIS lyric workflow coordinator with explicit resolution and display owners."""

from __future__ import annotations

import asyncio
import logging

from ..config import DEFAULT_LYRICS_SOURCES
from ..display.coordinator import DisplayCoordinator
from ..display.models import ResolutionState
from ..lyrics.ownership import SourceOwnershipCoordinator
from ..lyrics.sources import LyricsSourceKind
from ..lyrics.workflow import DocumentResolution, NoLyricsResolution, ResolverPort
from .mpris_adapter import MprisPlaybackAdapter
from .mpris_display import MprisDisplayBinding
from .mpris_playback import PlaybackSample
from .mpris_resolution import MprisResolutionSession
from .mpris_track import TrackCommit

logger = logging.getLogger(__name__)


class MprisLyricsCoordinator:
    """Coordinate stable MPRIS commits, lyric ownership, and display publication."""

    def __init__(
        self,
        display: DisplayCoordinator,
        *,
        ownership: SourceOwnershipCoordinator,
        resolver: ResolverPort,
        playback_adapter: MprisPlaybackAdapter | None = None,
        lyrics_sources: list[str] | None = None,
    ) -> None:
        """Create the coordinator from application-owned dependencies."""
        adapter = playback_adapter if playback_adapter is not None else MprisPlaybackAdapter()
        self._ownership = ownership
        self._resolution = MprisResolutionSession(
            ownership=ownership,
            resolver=resolver,
            playback_adapter=adapter,
            lyrics_sources=lyrics_sources if lyrics_sources is not None else list(DEFAULT_LYRICS_SOURCES),
        )
        self._display_binding = MprisDisplayBinding(
            display,
            ownership=ownership,
            playback_adapter=adapter,
        )
        self._load_task: asyncio.Task[None] | None = None
        self._load_tasks: set[asyncio.Task[None]] = set()
        self._current_commit: TrackCommit | None = None
        self._content_owner = "none"
        self._empty_since: float | None = None
        self._ownership_revision = self._ownership.revision

    @property
    def load_task(self) -> asyncio.Task[None] | None:
        """Return the active generation task for lifecycle tests and diagnostics."""
        return self._load_task

    @property
    def current_commit(self) -> TrackCommit | None:
        """Return the latest commit currently owned by the lyric workflow."""
        return self._current_commit

    @property
    def content_owner(self) -> str:
        """Return the current lyric content owner state."""
        return self._content_owner

    async def start(self) -> None:
        """Reopen resolver workers and create the shared lyric HTTP session."""
        await self._resolution.start()

    async def stop(self) -> None:
        """Cancel generation work, close resources, and reset display ownership."""
        tasks = tuple(self._load_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._load_task = None
        await self._resolution.stop()
        self._reset()

    def set_lyrics_sources(self, sources: list[str]) -> None:
        """Replace the ordered source plan and reload the current track."""
        updated = list(sources)
        if updated == list(self._resolution.lyrics_sources):
            return
        self._resolution.set_lyrics_sources(updated)
        self._resolution.reset_memory()
        self._force_reload()

    def set_cache_enabled(self, enabled: bool) -> None:
        """Toggle persistent lyric caching and reload the current track."""
        self._resolution.set_cache_enabled(enabled)
        self._force_reload()

    def set_prefer_best(self, enabled: bool) -> None:
        """Toggle best-result arbitration and reload the current track."""
        self._resolution.set_prefer_best(enabled)
        self._force_reload()

    def set_fuzzy(self, enabled: bool) -> None:
        """Toggle fuzzy matching and reload the current track."""
        self._resolution.set_fuzzy(enabled)
        self._force_reload()

    async def clear_cache(self) -> None:
        """Clear persistent lyric cache data through the resolution session."""
        await self._resolution.clear_cache()

    def on_playback_commit(self, commit: TrackCommit) -> None:
        """Start resolution for a stable playback transition."""
        self._schedule_load(commit)

    def on_playback_sample(self, sample: PlaybackSample) -> None:
        """Apply one normalized playback sample to the active lyric timeline."""
        current = self._current_commit
        self._display_binding.observe_sample(sample, current)
        if not sample.transitioning:
            self._ensure_content_owner()
            current = self._current_commit
        if sample.transitioning or self._content_owner != "external" or current is None:
            return
        self._display_binding.publish_external_sample(current, sample)

    def handle_no_player(self, now: float) -> bool:
        """Reset the lyric state after a sustained period without a player."""
        if self._current_commit is None and self._content_owner == "none":
            return False
        if self._empty_since is None:
            self._empty_since = now
            return False
        if now - self._empty_since < 0.35:
            return False
        self._reset()
        return True

    def reset(self) -> None:
        """Clear lyric state while retaining resolver configuration."""
        self._reset()

    async def _load_song(self, commit: TrackCommit) -> None:
        self._ownership.select_external()
        resolving_observation = self._resolution.resolving_observation(
            commit,
            self._display_binding.last_observation,
        )
        self._display_binding.publish_resolution(resolving_observation, ResolutionState.RESOLVING)
        result = await self._resolution.resolve(commit, self._display_binding.last_observation)
        if self._current_commit != commit:
            return
        decision = result.decision
        if isinstance(decision, NoLyricsResolution):
            self._content_owner = "none"
            if not self._select_late_live_source():
                logger.info(
                    "MPRIS %r / %r -> no lyrics: %s",
                    commit.info.title,
                    commit.info.artist,
                    decision.reason,
                )
                self._display_binding.publish_resolution(resolving_observation, ResolutionState.NOT_FOUND)
            return
        if decision.source_kind is LyricsSourceKind.LIVE:
            self._content_owner = "live"
            self._ownership_revision = self._ownership.revision
            match = self._ownership.current_match(result.info.metadata())
            if match is None:
                self._content_owner = "none"
                self._display_binding.publish_resolution(resolving_observation, ResolutionState.NOT_FOUND)
                return
            self._ownership.select_live(match.client_id)
            self._display_binding.publish_document(match.document, result.info, commit=commit)
            return
        if isinstance(decision, DocumentResolution) and self._select_late_live_source(
            before_source=decision.source_id
        ):
            return
        if not isinstance(decision, DocumentResolution):
            raise TypeError(f"unsupported resolution decision: {type(decision).__name__}")
        self._content_owner = "external"
        self._ownership_revision = self._ownership.revision
        latest = self._display_binding.last_observation
        self._display_binding.reconcile(
            commit,
            decision.document.lines,
            decision.duration_s,
            latest.position_s if latest is not None else None,
        )
        logger.info(
            "MPRIS %r / %r -> %d %s lines",
            commit.info.title,
            commit.info.artist,
            len(decision.document.lines),
            decision.source_id,
        )
        self._display_binding.publish_document(decision.document, result.info, commit=commit)

    def _schedule_load(self, commit: TrackCommit) -> None:
        current = self._current_commit
        if current is not None and commit != current and commit.generation <= current.generation:
            commit = TrackCommit(
                current.generation + 1,
                commit.player_name,
                commit.info,
                commit.start_position,
                commit.player_identity,
            )
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()
        self._display_binding.observe_commit(commit)
        self._current_commit = commit
        self._content_owner = "resolving"
        task = asyncio.create_task(self._load_song(commit), name="kotonoha-mpris-lyrics")
        self._load_task = task
        self._load_tasks.add(task)
        task.add_done_callback(self._load_finished)

    def _load_finished(self, task: asyncio.Task[None]) -> None:
        self._load_tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.warning("MPRIS lyrics load failed: %s", error)

    def _force_reload(self) -> None:
        current = self._current_commit
        if current is None:
            return
        self._schedule_load(
            TrackCommit(
                current.generation + 1,
                current.player_name,
                current.info,
                player_identity=current.player_identity,
            )
        )

    def _ensure_content_owner(self) -> None:
        if self._content_owner == "live" and not self._ownership.live_active:
            self._force_reload()
            return
        if self._content_owner != "none" or self._current_commit is None:
            return
        self._select_late_live_source()

    def _select_late_live_source(self, *, before_source: str | None = None) -> bool:
        current = self._current_commit
        if current is None:
            return False
        revision = self._ownership.revision
        if revision == self._ownership_revision:
            return False
        self._ownership_revision = revision
        sources = self._resolution.lyrics_sources
        if self._resolution.live_source_id not in sources:
            return False
        if before_source is not None:
            try:
                if sources.index(self._resolution.live_source_id) >= sources.index(before_source):
                    return False
            except ValueError:
                return False
        match = self._ownership.current_match(current.info.metadata())
        if match is None:
            return False
        self._ownership.select_live(match.client_id)
        self._content_owner = "live"
        self._display_binding.publish_document(match.document, current.info, commit=current)
        return True

    def _reset(self) -> None:
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()
        self._current_commit = None
        self._content_owner = "none"
        self._empty_since = None
        self._ownership.select_standalone()
        self._ownership_revision = self._ownership.revision
        self._display_binding.reset()


__all__ = ["MprisLyricsCoordinator"]
