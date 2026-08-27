"""Cider's low-frequency HTTP playback and lyrics provider."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Protocol

from ..display.coordinator import DisplayCoordinator
from ..display.models import ResolutionState
from ..lyrics.cider_api import CiderLyricsPayloadError
from ..lyrics.models import LyricsDocument
from ..lyrics.ownership import SourceOwnershipCoordinator
from ..playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity
from .cider_client import CiderApiClient, CiderApiError, CiderLyricsNotFound

logger = logging.getLogger(__name__)

CIDER_API_CLIENT_ID = "cider-api"
CIDER_API_POLL_INTERVAL = 1.0


class CiderApiPort(Protocol):
    """The async Cider capability required by the provider workflow."""

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    def set_token(self, token: str | None) -> None: ...

    async def playback(self, *, observed_at: float) -> PlaybackObservation: ...

    async def lyrics(
        self,
        track: TrackIdentity,
        *,
        translation_language: str | None,
    ) -> LyricsDocument: ...


class CiderApiProvider:
    """Poll Cider playback, fetch one lyric document per track, and publish frames.

    The provider owns the HTTP and task lifecycles. Cider API data is observed
    through the source ownership coordinator so an active MPRIS resolution can retain
    ownership while the Cider track remains available as a live candidate.
    """

    def __init__(
        self,
        *,
        display: DisplayCoordinator,
        ownership: SourceOwnershipCoordinator,
        client: CiderApiPort | None = None,
        translation_language: str | None = None,
        poll_interval: float = CIDER_API_POLL_INTERVAL,
        enabled: bool = True,
    ) -> None:
        if poll_interval <= 0.0:
            raise ValueError("Cider API poll interval must be positive")
        self._display = display
        self._ownership = ownership
        self._client = client if client is not None else CiderApiClient()
        self._translation_language = translation_language
        self._poll_interval = poll_interval
        self._enabled = enabled
        self._task: asyncio.Task[None] | None = None
        self._lyrics_task: asyncio.Task[None] | None = None
        self._lyrics_tasks: set[asyncio.Task[None]] = set()
        self._generation = 0
        self._attempted_track_ref: str | None = None
        self._observation: PlaybackObservation | None = None
        self._document: LyricsDocument | None = None

    async def start(self) -> None:
        """Start the owned HTTP session and low-frequency polling task."""
        if self._task is not None and not self._task.done():
            return
        await self._client.start()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel polling and lyric resolution before closing the HTTP session."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._cancel_lyrics()
        self._clear_content(publish=True)
        await self._client.close()

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable Cider as a configured lyric source."""
        updated = bool(enabled)
        if updated == self._enabled:
            return
        self._enabled = updated
        if not updated:
            self._cancel_current_lyrics()
            self._clear_content(publish=True)
        else:
            self._attempted_track_ref = None

    def set_token(self, token: str | None) -> None:
        """Update the optional Cider credential without restarting the provider."""
        self._client.set_token(token)

    def set_translation_language(self, language: str | None) -> None:
        """Change the optional Cider translation language for the current track."""
        if language == self._translation_language:
            return
        self._translation_language = language
        self._attempted_track_ref = None
        self._document = None
        self._generation += 1
        self._cancel_current_lyrics()
        self._ownership.clear_client(CIDER_API_CLIENT_ID)

    async def _run(self) -> None:
        try:
            while True:
                try:
                    if self._enabled:
                        await self._poll_once()
                except asyncio.CancelledError:
                    raise
                except CiderApiError as exc:
                    logger.debug("Cider API playback unavailable: %s", exc)
                except (CiderLyricsPayloadError, ValueError) as exc:
                    logger.warning("Cider API response rejected: %s", exc)
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            raise

    async def _poll_once(self) -> None:
        observed_at = time.monotonic()
        observation = await self._client.playback(observed_at=observed_at)
        track_ref = observation.track.track_ref if observation.track is not None else None
        previous_ref = (
            self._observation.track.track_ref
            if self._observation is not None and self._observation.track
            else None
        )
        if track_ref != previous_ref:
            self._generation += 1
            await self._cancel_lyrics()
            self._document = None
            self._attempted_track_ref = None
            self._ownership.clear_client(CIDER_API_CLIENT_ID)
        self._observation = observation
        if observation.track is not None and self._attempted_track_ref != track_ref:
            self._attempted_track_ref = track_ref
            self._schedule_lyrics(observation, self._generation)
        resolving = (
            observation.track is not None
            and self._document is None
            and self._lyrics_task is not None
            and not self._lyrics_task.done()
        )
        resolution = (
            ResolutionState.RESOLVING
            if resolving
            else ResolutionState.from_facts(observation, self._document)
        )
        self._publish(observation, self._document, resolution)

    async def _load_lyrics(self, observation: PlaybackObservation, generation: int) -> None:
        track = observation.track
        if track is None:
            return
        try:
            document = await self._client.lyrics(
                track,
                translation_language=self._translation_language,
            )
        except asyncio.CancelledError:
            raise
        except CiderLyricsNotFound as exc:
            logger.debug("Cider lyrics unavailable for %s: %s", track.stable_id, exc)
            document = None
        except (CiderApiError, CiderLyricsPayloadError, ValueError) as exc:
            logger.warning("Cider lyrics request failed for %s: %s", track.stable_id, exc)
            document = None
        if generation != self._generation or self._observation is None:
            return
        current_track = self._observation.track
        if current_track is None or current_track.track_ref != track.track_ref:
            return
        self._document = document
        self._publish(
            self._observation,
            document,
            ResolutionState.AVAILABLE if document is not None else ResolutionState.NOT_FOUND,
        )

    def _publish(
        self,
        observation: PlaybackObservation,
        document: LyricsDocument | None,
        resolution: ResolutionState,
    ) -> None:
        """Publish one canonical frame and retain it as a source candidate."""
        self._ownership.observe(CIDER_API_CLIENT_ID, observation, document)
        track_ref = observation.track.track_ref if observation.track is not None else None
        self._ownership.observe_clock(
            CIDER_API_CLIENT_ID,
            track_ref,
            observation.position_s,
            observation.status is PlaybackStatus.PLAYING,
        )
        if self._ownership.accepts(CIDER_API_CLIENT_ID):
            self._display.publish_resolution(observation, document, resolution)

    async def _cancel_lyrics(self) -> None:
        self._cancel_current_lyrics()
        tasks = tuple(self._lyrics_tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _schedule_lyrics(self, observation: PlaybackObservation, generation: int) -> None:
        """Create a lyric task and retain it until its result is inspected."""
        task = asyncio.create_task(self._load_lyrics(observation, generation))
        self._lyrics_task = task
        self._lyrics_tasks.add(task)
        task.add_done_callback(self._lyrics_finished)

    def _cancel_current_lyrics(self) -> None:
        """Request cancellation without dropping the provider's task ownership."""
        task = self._lyrics_task
        self._lyrics_task = None
        if task is not None and not task.done():
            task.cancel()

    def _lyrics_finished(self, task: asyncio.Task[None]) -> None:
        """Remove a finished task after retrieving unexpected failures."""
        self._lyrics_tasks.discard(task)
        if self._lyrics_task is task:
            self._lyrics_task = None
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.warning("Cider lyrics task failed: %s", error)

    def _clear_content(self, *, publish: bool) -> None:
        """Remove the Cider candidate without changing another source's mode."""
        self._generation += 1
        self._document = None
        self._observation = None
        self._attempted_track_ref = None
        self._ownership.clear_client(CIDER_API_CLIENT_ID)
        if publish and self._ownership.accepts(CIDER_API_CLIENT_ID):
            empty_observation = PlaybackObservation(
                adapter_id="cider",
                player_id=CIDER_API_CLIENT_ID,
                track=None,
                status=PlaybackStatus.STOPPED,
                position_s=None,
                duration_s=None,
                observed_at=time.monotonic(),
            )
            self._display.publish(empty_observation, None)


__all__ = ["CIDER_API_CLIENT_ID", "CIDER_API_POLL_INTERVAL", "CiderApiPort", "CiderApiProvider"]
