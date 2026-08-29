"""Cider's low-frequency HTTP playback and lyrics provider."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Protocol

from ..app.source_contracts import SourcePublicationPort
from ..async_task import create_owned_task, wait_for_owned
from ..display.contracts import CiderDisplayPort
from ..display.models import ResolutionState
from ..lyrics.cider_api import CiderLyricsPayloadError
from ..lyrics.models import LyricsDocument
from ..playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity
from .cider_client import CiderApiError, CiderLyricsNotFound

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
        display: CiderDisplayPort,
        ownership: SourcePublicationPort,
        client: CiderApiPort,
        translation_language: str | None = None,
        poll_interval: float = CIDER_API_POLL_INTERVAL,
        enabled: bool = True,
    ) -> None:
        if poll_interval <= 0.0:
            raise ValueError("Cider API poll interval must be positive")
        self._display = display
        self._ownership = ownership
        self._client = client
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
        self._last_log_publish_key: tuple[object, ...] | None = None

    async def start(self) -> None:
        """Start the owned HTTP session and low-frequency polling task."""
        task = self._task
        if task is not None:
            if not task.done():
                return
            self._task = None
        try:
            await self._client.start()
            task = create_owned_task(self._run(), name="kotonoha-cider-playback")
        except asyncio.CancelledError:
            await self._close_failed_start_client()
            raise
        except (CiderApiError, OSError, TimeoutError, RuntimeError, TypeError, ValueError):
            await self._close_failed_start_client()
            raise
        self._task = task
        task.add_done_callback(self._playback_task_finished)

    async def _close_failed_start_client(self) -> None:
        """Release a client acquired by a failed provider startup."""
        try:
            await self._close_client()
        except (CiderApiError, OSError, TimeoutError, RuntimeError, ValueError) as exc:
            logger.warning("Could not close Cider client after startup failure: %s", exc)

    def _playback_task_finished(self, task: asyncio.Task[None]) -> None:
        """Observe unexpected polling failures when no later stop occurs."""
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.error("Cider playback task failed: %s", error)

    async def stop(self) -> None:
        """Cancel polling and lyric resolution before closing the HTTP session."""
        task = self._task
        self._task = None
        cancellation_requested = False
        try:
            if task is not None:
                if not task.done():
                    task.cancel()
                cancellation_requested = await wait_for_owned(task)
        finally:
            try:
                cancellation_requested |= await self._cancel_lyrics()
            finally:
                try:
                    self._clear_content(publish=True)
                finally:
                    cancellation_requested |= await self._close_client()
        if cancellation_requested:
            raise asyncio.CancelledError

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
            cancellation_requested = await self._cancel_lyrics()
            if cancellation_requested:
                raise asyncio.CancelledError
            self._document = None
            self._attempted_track_ref = None
            self._last_log_publish_key = None
            self._ownership.clear_client(CIDER_API_CLIENT_ID)
            logger.info(
                "Cider playback changed: generation=%d track=%r / %r ref=%r "
                "status=%s position=%s",
                self._generation,
                observation.track.title if observation.track is not None else "",
                observation.track.artist if observation.track is not None else "",
                track_ref,
                observation.status,
                _position_text(observation.position_s),
            )
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
            logger.debug(
                "Cider lyrics response discarded: generation=%d track_ref=%r is no longer current",
                generation,
                track.track_ref,
            )
            return
        self._document = document
        if document is None:
            logger.debug(
                "Cider lyric candidate unavailable: generation=%d track=%r / %r "
                "source_slot='cider' outcome=not_found",
                generation,
                track.title,
                track.artist,
            )
        else:
            source_label = document.source_name if document.source_name is not None else document.source_id
            logger.debug(
                "Cider lyric candidate ready: generation=%d track=%r / %r "
                "source_slot='cider' lyric_source=%r source_id=%r timing=%s lines=%d",
                generation,
                track.title,
                track.artist,
                source_label,
                document.source_id,
                document.timing,
                len(document.lines),
            )
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
        accepted = self._ownership.accepts(CIDER_API_CLIENT_ID)
        source_label = (
            document.source_name
            if document is not None and document.source_name is not None
            else document.source_id
            if document is not None
            else "none"
        )
        publish_key = (
            observation.track.track_ref if observation.track is not None else None,
            accepted,
            self._ownership.mode,
            document.source_id if document is not None else None,
            document.source_name if document is not None else None,
        )
        if publish_key != self._last_log_publish_key:
            self._last_log_publish_key = publish_key
            logger.debug(
                "Cider lyric candidate: outcome=%s display_owner=%r source_slot='cider' "
                "lyric_source=%r source_id=%r track_ref=%r",
                "displayed" if accepted else "not_displayed",
                self._ownership.mode,
                source_label,
                document.source_id if document is not None else None,
                publish_key[0],
            )
        if accepted:
            self._display.publish_resolution(observation, document, resolution)

    async def _cancel_lyrics(self) -> bool:
        self._cancel_current_lyrics()
        tasks = tuple(self._lyrics_tasks)
        if not tasks:
            return False
        joined = asyncio.gather(*tasks, return_exceptions=True)
        return await wait_for_owned(joined)

    async def _close_client(self) -> bool:
        """Close the client through an owned task and preserve caller cancellation."""
        close_task = create_owned_task(self._client.close(), name="kotonoha-cider-close")
        return await wait_for_owned(close_task)

    def _schedule_lyrics(self, observation: PlaybackObservation, generation: int) -> None:
        """Create a lyric task and retain it until its result is inspected."""
        task = create_owned_task(
            self._load_lyrics(observation, generation),
            name="kotonoha-cider-lyrics",
        )
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
        self._last_log_publish_key = None
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


def _position_text(position: float | None) -> str:
    """Format an optional Cider playback position for logs."""
    return "-" if position is None else f"{position:.3f}s"


__all__ = ["CIDER_API_CLIENT_ID", "CIDER_API_POLL_INTERVAL", "CiderApiPort", "CiderApiProvider"]
