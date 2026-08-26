"""MPRIS lyric resolution, ownership, and display-timeline coordination."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace

from ..config import DEFAULT_LYRICS_SOURCES
from ..display.coordinator import DisplayCoordinator
from ..display.models import EMPTY_FRAME, DisplayState
from ..display.timeline import find_current_index
from ..lyrics.hint import from_player
from ..lyrics.http import LyricsSession
from ..lyrics.models import LyricLine, LyricsDocument
from ..lyrics.ownership import SourceOwnershipCoordinator
from ..lyrics.sources import LyricsSourceKind
from ..lyrics.workflow import (
    DocumentResolution,
    LyricsResolutionWorkflow,
    NoLyricsResolution,
    ResolverPort,
    SourcePlan,
)
from ..playback.coordinator import PlaybackSample
from ..playback.models import PlaybackObservation, PlaybackStatus
from .mpris_adapter import MprisPlaybackAdapter
from .mpris_http import new_lyrics_session
from .mpris_timeline import MprisTimeline
from .mpris_track import CumulativeLengthDetector, TrackCommit, TrackInfo, lyrics_lookup_reason

logger = logging.getLogger(__name__)


class MprisLyricsCoordinator:
    """Own one MPRIS lyric workflow from stable commit to display frame."""

    def __init__(
        self,
        display: DisplayCoordinator,
        *,
        ownership: SourceOwnershipCoordinator,
        resolver: ResolverPort,
        playback_adapter: MprisPlaybackAdapter | None = None,
        lyrics_sources: list[str] | None = None,
    ) -> None:
        """Create a coordinator from one resolver and one live-source owner."""
        self._display = display
        self._lyrics_sources = list(lyrics_sources) if lyrics_sources is not None else list(DEFAULT_LYRICS_SOURCES)
        self._ownership = ownership
        self._resolver: ResolverPort = resolver
        self._live_source_id = self._resolver.live_source_id
        self._playback_adapter = playback_adapter if playback_adapter is not None else MprisPlaybackAdapter()
        self._workflow = LyricsResolutionWorkflow(self._resolver)
        self._lyrics_session: LyricsSession | None = None
        self._length_detector = CumulativeLengthDetector()
        self._empty_since: float | None = None
        self._timeline = MprisTimeline()
        self._lines: list[LyricLine] = []
        self._document: LyricsDocument | None = None
        self._last_index = -2
        self._load_task: asyncio.Task[None] | None = None
        self._load_tasks: set[asyncio.Task[None]] = set()
        self._current_commit: TrackCommit | None = None
        self._content_owner = "none"
        self._ownership_revision = self._ownership.revision
        self._last_observation: PlaybackObservation | None = None

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
        """Create the shared HTTP session for lyric resolution."""
        if self._lyrics_session is None:
            self._lyrics_session = new_lyrics_session()

    async def stop(self) -> None:
        """Cancel generation tasks and close the owned HTTP session."""
        tasks = tuple(self._load_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._load_task = None
        await self._workflow.cancel_all()
        await self._resolver.close()
        if self._lyrics_session is not None:
            await self._lyrics_session.close()
            self._lyrics_session = None

    def set_lyrics_sources(self, sources: list[str]) -> None:
        """Replace the ordered source plan and reload the current track."""
        updated = list(sources)
        if updated == self._lyrics_sources:
            return
        self._lyrics_sources = updated
        self._resolver.reset_memory()
        self._force_reload()

    def set_cache_enabled(self, enabled: bool) -> None:
        """Toggle the resolver cache and reload the current track."""
        self._resolver.set_cache_enabled(bool(enabled))
        self._force_reload()

    def set_prefer_best(self, enabled: bool) -> None:
        """Toggle best-result arbitration and reload the current track."""
        self._resolver.set_prefer_best(bool(enabled))
        self._force_reload()

    def set_fuzzy(self, enabled: bool) -> None:
        """Toggle fuzzy matching and reload the current track."""
        self._resolver.set_fuzzy(bool(enabled))
        self._force_reload()

    async def clear_cache(self) -> None:
        """Clear persistent lyric cache data through the resolver owner."""
        await self._resolver.clear_cache()

    def on_playback_commit(self, commit: TrackCommit) -> None:
        """Start resolution for a stable playback transition."""
        self._schedule_load(commit)

    def on_playback_sample(self, sample: PlaybackSample) -> None:
        """Apply one normalized playback sample to the active lyric timeline."""
        observation = sample.observation
        self._last_observation = observation
        observed_at = observation.observed_at
        position = observation.position_s
        current = self._current_commit
        if position is not None and not sample.transitioning and current is not None:
            self._timeline.calibrate(current, position, observed_at)

        if not sample.transitioning:
            self._ensure_content_owner()
            current = self._current_commit
        if sample.transitioning or self._content_owner != "external" or current is None:
            return

        playing = observation.status is PlaybackStatus.PLAYING
        if position is not None:
            position = max(0.0, position - self._timeline.offset)
        live_timing = self._ownership.current_timing(current.info.metadata())
        if live_timing is not None and live_timing.current_time is not None:
            position = live_timing.current_time
            if live_timing.is_playing is not None:
                playing = live_timing.is_playing
        if position is None:
            return
        self._display.tick(position, playing)
        index = find_current_index(self._lines, position)
        if index != self._last_index:
            self._last_index = index
            self._emit(current.info, position, playing, player_name=current.player_name, observed_at=observed_at)

    def handle_no_player(self, now: float) -> bool:
        """Return whether a sustained no-player period reset the lyric state."""
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
        self._lines = []
        self._document = None
        self._last_index = -2
        self._ownership.select_external()
        resolving_observation = self._playback_adapter.observe(
            commit.info,
            player_name=commit.player_name,
            status="Playing",
            position_s=0.0,
            observed_at=time.monotonic(),
        )
        self._display.publish(resolving_observation, None, state=DisplayState.RESOLVING)
        info = commit.info
        length_trusted = self._length_detector.observe(
            commit.player_identity, info.track_id, info.length_s, time.monotonic()
        )
        live_timing = self._ownership.current_timing(info.metadata())
        if live_timing is not None and live_timing.duration_s is not None:
            if live_timing.duration_s != info.length_s:
                logger.debug(
                    "Using matching Cider duration %.3fs instead of MPRIS %s",
                    live_timing.duration_s,
                    info.length_s,
                )
            info = replace(info, length_s=live_timing.duration_s)
        elif not length_trusted and info.length_s is not None:
            logger.info(
                "Ignoring %r's length %.0fs for %r: it advances with the clock, so it "
                "counts session playtime rather than this track",
                commit.player_name,
                info.length_s,
                info.title,
            )
            info = replace(info, length_s=None)

        skip_reason = lyrics_lookup_reason(info)
        if skip_reason is not None:
            logger.info("Skipping lyric lookup for %r: %s", info.title, skip_reason)
            self._content_owner = "none"
            return
        try:
            hint = from_player(commit.player_identity, commit.player_name, commit.info.track_id, commit.info.url)
            decision = await self._workflow.resolve(
                self._lyrics_session,
                info.metadata(),
                SourcePlan.from_sources(self._lyrics_sources),
                generation=commit.generation,
                hint=hint,
            )
        except asyncio.CancelledError:
            raise
        if self._current_commit != commit:
            return
        if isinstance(decision, NoLyricsResolution):
            self._content_owner = "none"
            if not self._select_late_live_source():
                unreachable = decision.unreachable_sources
                answered = [source for source in self._lyrics_sources if source not in unreachable]
                logger.info(
                    "MPRIS %r / %r -> no lyrics from %s%s",
                    commit.info.title,
                    commit.info.artist,
                    ", ".join(answered) or "no source",
                    f" ({', '.join(sorted(unreachable))} could not be reached)" if unreachable else "",
                )
            return
        if decision.source_kind is LyricsSourceKind.LIVE:
            self._content_owner = "live"
            self._document = decision.document
            self._ownership_revision = self._ownership.revision
            self._lines = list(self._document.lines)
            match = self._ownership.current_match(info.metadata())
            if match is None:
                self._content_owner = "none"
                return
            self._ownership.select_live(match.client_id)
            self._publish_document(decision.document, info)
            return
        if isinstance(decision, DocumentResolution) and self._select_late_live_source(
            before_source=decision.source_id
        ):
            return
        if not isinstance(decision, DocumentResolution):
            raise TypeError(f"unsupported resolution decision: {type(decision).__name__}")
        self._content_owner = "external"
        self._document = decision.document
        self._ownership_revision = self._ownership.revision
        self._lines = list(self._document.lines)
        self._timeline.reconcile(
            commit,
            decision.document.lines,
            decision.duration_s,
            self._last_observation.position_s if self._last_observation is not None else None,
        )
        logger.info(
            "MPRIS %r / %r -> %d %s lines",
            commit.info.title,
            commit.info.artist,
            len(self._lines),
            decision.source_id,
        )

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
        self._timeline.observe_commit(commit)
        self._current_commit = commit
        self._content_owner = "resolving"
        task = asyncio.create_task(self._load_song(commit))
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
        if self._current_commit is None:
            return False
        revision = self._ownership.revision
        if revision == self._ownership_revision:
            return False
        self._ownership_revision = revision
        if self._live_source_id not in self._lyrics_sources:
            return False
        if before_source is not None:
            try:
                if self._lyrics_sources.index(self._live_source_id) >= self._lyrics_sources.index(before_source):
                    return False
            except ValueError:
                return False
        match = self._ownership.current_match(self._current_commit.info.metadata())
        if match is None:
            return False
        self._ownership.select_live(match.client_id)
        self._content_owner = "live"
        self._document = match.document
        self._lines = list(match.document.lines)
        self._publish_document(match.document, self._current_commit.info)
        return True

    def _emit(
        self,
        info: TrackInfo,
        position: float,
        playing: bool,
        *,
        player_name: str | None = None,
        observed_at: float | None = None,
    ) -> None:
        """Publish the current lyric lines at one normalized playback position."""
        document = self._document
        if document is None:
            logger.warning("Cannot publish MPRIS lyric position without a canonical document")
            return
        current_commit = self._current_commit
        resolved_player_name = (
            player_name
            if player_name is not None
            else current_commit.player_name
            if current_commit is not None
            else ""
        )
        self._publish_document(
            document,
            info,
            position_s=position,
            playing=playing,
            player_name=resolved_player_name,
            observed_at=time.monotonic() if observed_at is None else observed_at,
        )

    def _publish_document(
        self,
        document: LyricsDocument,
        info: TrackInfo,
        *,
        position_s: float | None = None,
        playing: bool | None = None,
        player_name: str | None = None,
        observed_at: float | None = None,
    ) -> None:
        """Publish a source-owned document against the latest MPRIS observation."""
        latest = self._last_observation
        if (
            latest is not None
            and latest.track is not None
            and latest.track.title == info.title
            and position_s is None
            and playing is None
            and player_name is None
            and observed_at is None
        ):
            observation = latest
        else:
            current_commit = self._current_commit
            resolved_player_name = (
                player_name
                if player_name is not None
                else current_commit.player_name
                if current_commit is not None
                else latest.player_id
                if latest is not None
                else ""
            )
            resolved_position = (
                position_s
                if position_s is not None
                else latest.position_s
                if latest is not None and latest.position_s is not None
                else 0.0
            )
            resolved_playing = (
                playing
                if playing is not None
                else latest is None or latest.status is PlaybackStatus.PLAYING
            )
            observation = self._playback_adapter.observe(
                info,
                player_name=resolved_player_name,
                status="Playing" if resolved_playing else "Paused",
                position_s=max(0.0, resolved_position),
                observed_at=time.monotonic() if observed_at is None else observed_at,
            )
        self._display.publish(observation, document)

    def _reset(self) -> None:
        if self._load_task is not None and not self._load_task.done():
            self._load_task.cancel()
        self._current_commit = None
        self._lines = []
        self._document = None
        self._last_index = -2
        self._content_owner = "none"
        self._empty_since = None
        self._timeline.reset()
        self._ownership.select_standalone()
        self._ownership_revision = self._ownership.revision
        self._display.publish_frame(EMPTY_FRAME)


__all__ = ["MprisLyricsCoordinator"]
