"""MPRIS lyric-resolution session and its restartable resources."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, replace

from ..app.source_contracts import SourceClockPort
from ..async_task import create_owned_task, wait_for_owned
from ..config import DEFAULT_LYRICS_SOURCES
from ..lyrics.artifact import LyricsArtifact
from ..lyrics.cache import (
    CacheDeleteResult,
    CacheWriteResult,
    LyricsCacheEntry,
    LyricsCacheKey,
    LyricsCacheMode,
    LyricsCacheQuery,
)
from ..lyrics.hint import from_player
from ..lyrics.http import LyricsSession
from ..lyrics.workflow import (
    LyricsResolutionWorkflow,
    NoLyricsResolution,
    ResolutionDecision,
    ResolverPort,
    SourcePlan,
)
from ..playback.models import PlaybackObservation
from .mpris_adapter import MprisPlaybackAdapter
from .mpris_http import new_lyrics_session
from .mpris_track import CumulativeLengthDetector, TrackCommit, TrackInfo, lyrics_lookup_reason

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MprisResolutionResult:
    """Resolution output plus the adjusted metadata used for matching and timing."""

    decision: ResolutionDecision
    info: TrackInfo
    resolving_observation: PlaybackObservation


class MprisResolutionSession:
    """Own resolver workflow resources and normalize one MPRIS lookup request."""

    def __init__(
        self,
        *,
        ownership: SourceClockPort,
        resolver: ResolverPort,
        playback_adapter: MprisPlaybackAdapter,
        lyrics_sources: list[str] | None = None,
    ) -> None:
        """Create a resolution session without opening network or worker resources."""
        self._ownership = ownership
        self._resolver = resolver
        self._playback_adapter = playback_adapter
        self._lyrics_sources = list(lyrics_sources) if lyrics_sources is not None else list(DEFAULT_LYRICS_SOURCES)
        self._workflow = LyricsResolutionWorkflow(resolver)
        self._lyrics_session: LyricsSession | None = None
        self._length_detector = CumulativeLengthDetector()

    @property
    def live_source_id(self) -> str:
        """Return the resolver slot used by the live player source."""
        return self._resolver.live_source_id

    @property
    def lyrics_sources(self) -> tuple[str, ...]:
        """Return the immutable source order used by the next lookup."""
        return tuple(self._lyrics_sources)

    async def start(self) -> None:
        """Reopen resolver workers and create the shared HTTP session."""
        new_session: LyricsSession | None = None
        try:
            if self._lyrics_session is None:
                new_session = new_lyrics_session()
            self._resolver.start()
        except (OSError, RuntimeError, TimeoutError, ValueError):
            if new_session is not None:
                await self._close_failed_start_session(new_session)
            raise
        if new_session is not None:
            self._lyrics_session = new_session

    async def _close_failed_start_session(self, session: LyricsSession) -> None:
        """Finish closing a session acquired by a failed startup attempt.

        Startup owns this temporary session before it is assigned to the long-lived
        field.  Shielding the close keeps a caller cancellation from leaking it;
        the cancellation is reported again after the close has completed.
        """
        close_task = create_owned_task(session.close(), name="kotonoha-mpris-http-rollback")
        cancellation_requested = False
        try:
            cancellation_requested = await wait_for_owned(close_task)
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            logger.warning("Could not close MPRIS HTTP session after startup failure: %s", exc)
        if cancellation_requested:
            raise asyncio.CancelledError

    async def stop(self) -> None:
        """Cancel workflow tasks and close all resolver-owned resources."""
        cancellation_requested = False
        try:
            workflow_stop = create_owned_task(
                self._workflow.cancel_all(),
                name="kotonoha-mpris-workflow-stop",
            )
            cancellation_requested = await wait_for_owned(workflow_stop)
        finally:
            try:
                resolver_close = create_owned_task(
                    self._resolver.close(),
                    name="kotonoha-mpris-resolver-close",
                )
                cancellation_requested |= await wait_for_owned(resolver_close)
            finally:
                if self._lyrics_session is not None:
                    session = self._lyrics_session
                    try:
                        session_close = create_owned_task(
                            session.close(),
                            name="kotonoha-mpris-http-close",
                        )
                        cancellation_requested |= await wait_for_owned(session_close)
                    finally:
                        self._lyrics_session = None
        if cancellation_requested:
            raise asyncio.CancelledError

    def set_lyrics_sources(self, sources: list[str]) -> None:
        """Replace the ordered source plan for future resolution generations."""
        self._lyrics_sources = list(sources)
        self._resolver.reset_memory()

    def reset_memory(self) -> None:
        """Clear resolver negative memory after a source or policy change."""
        self._resolver.reset_memory()

    def set_cache_enabled(self, enabled: bool) -> None:
        """Apply cache policy through the resolver boundary."""
        self._resolver.set_cache_enabled(bool(enabled))

    def set_prefer_best(self, enabled: bool) -> None:
        """Apply result arbitration policy through the resolver boundary."""
        self._resolver.set_prefer_best(bool(enabled))

    def set_fuzzy(self, enabled: bool) -> None:
        """Apply matching policy through the resolver boundary."""
        self._resolver.set_fuzzy(bool(enabled))

    async def clear_cache(self) -> None:
        """Clear persistent resolver cache data."""
        await self._resolver.clear_cache()

    async def search_cache(self, query: LyricsCacheQuery) -> tuple[LyricsCacheEntry, ...]:
        """Search persisted cache metadata for the management workflow."""
        return await self._resolver.search_cache(query)

    async def get_cache(self, key: LyricsCacheKey) -> LyricsCacheEntry | None:
        """Read one persisted cache entry by provider-scoped identity."""
        return await self._resolver.get_cache(key)

    async def upsert_cache(
        self,
        artifact: LyricsArtifact,
        *,
        mode: LyricsCacheMode = LyricsCacheMode.MANUAL,
    ) -> CacheWriteResult:
        """Persist a validated result chosen by a future manual-selection workflow."""
        return await self._resolver.upsert_cache(artifact, mode=mode)

    async def update_cache(
        self,
        key: LyricsCacheKey,
        artifact: LyricsArtifact,
        *,
        mode: LyricsCacheMode = LyricsCacheMode.MANUAL,
    ) -> CacheWriteResult:
        """Update an existing cache record and record its selection mode."""
        return await self._resolver.update_cache(key, artifact, mode=mode)

    async def delete_cache(self, key: LyricsCacheKey) -> CacheDeleteResult:
        """Delete one persisted cache record."""
        return await self._resolver.delete_cache(key)

    async def delete_cache_many(self, keys: tuple[LyricsCacheKey, ...]) -> tuple[CacheDeleteResult, ...]:
        """Delete several persisted cache records in one cache-owned operation."""
        return await self._resolver.delete_cache_many(keys)

    async def resolve(
        self,
        commit: TrackCommit,
        latest_observation: PlaybackObservation | None,
    ) -> MprisResolutionResult:
        """Resolve one stable track after applying MPRIS-specific metadata policy."""
        info = self._trusted_info(commit)
        resolving_observation = self._resolving_observation(commit, latest_observation)
        skip_reason = lyrics_lookup_reason(info)
        if skip_reason is not None:
            return MprisResolutionResult(
                NoLyricsResolution(commit.generation, skip_reason),
                info,
                resolving_observation,
            )

        hint = from_player(commit.player_identity, commit.player_name, commit.info.track_id, commit.info.url)
        decision = await self._workflow.resolve(
            self._lyrics_session,
            info.metadata(),
            SourcePlan.from_sources(self._lyrics_sources),
            generation=commit.generation,
            hint=hint,
        )
        return MprisResolutionResult(decision, info, resolving_observation)

    def resolving_observation(
        self,
        commit: TrackCommit,
        latest_observation: PlaybackObservation | None,
    ) -> PlaybackObservation:
        """Build the playback facts shown while this commit is resolving."""
        return self._resolving_observation(commit, latest_observation)

    def _trusted_info(self, commit: TrackCommit) -> TrackInfo:
        """Reject cumulative session length and prefer a matching live duration."""
        info = commit.info
        length_trusted = self._length_detector.observe(
            commit.player_identity,
            info.track_id,
            info.length_s,
            time.monotonic(),
        )
        live_timing = self._ownership.current_timing(info.metadata())
        if live_timing is not None and live_timing.duration_s is not None:
            if live_timing.duration_s != info.length_s:
                # The live player has the authoritative track duration when its
                # metadata matches this MPRIS commit.
                logger.debug(
                    "Using matching live duration %.3fs instead of MPRIS %s",
                    live_timing.duration_s,
                    info.length_s,
                )
            return replace(info, length_s=live_timing.duration_s)
        if not length_trusted and info.length_s is not None:
            logger.info(
                "Ignoring %r's length %.0fs for %r: it advances with the clock, so it "
                "counts session playtime rather than this track",
                commit.player_name,
                info.length_s,
                info.title,
            )
            return replace(info, length_s=None)
        return info

    def _resolving_observation(
        self,
        commit: TrackCommit,
        latest: PlaybackObservation | None,
    ) -> PlaybackObservation:
        """Keep matching playback facts while the source workflow is pending."""
        if (
            latest is not None
            and latest.player_id == commit.player_name
            and latest.track is not None
            and latest.track.title == commit.info.title
            and latest.track.artist == commit.info.artist
        ):
            return latest
        return self._playback_adapter.observe(
            commit.info,
            player_name=commit.player_name,
            status="Playing",
            position_s=commit.start_position if commit.start_position is not None else 0.0,
            observed_at=time.monotonic(),
        )


__all__ = ["MprisResolutionResult", "MprisResolutionSession"]
