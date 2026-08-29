"""Application-owned display projection and timing workflow."""

from __future__ import annotations

import asyncio
import logging

from ..async_task import create_owned_task, wait_for_owned
from ..display.contracts import DisplayPublisher
from ..display.models import DisplayFrame, DisplayOptions, DisplayState, ResolutionState
from ..display.presentation import DisplayEngine
from ..display.timeline import TimelineEngine
from ..lyrics.models import LyricsDocument
from ..playback.models import PlaybackObservation, PlaybackStatus

DISPLAY_TICK_INTERVAL_S = 1.0 / 60.0
logger = logging.getLogger(__name__)


class DisplayCoordinator:
    """Own the normalized-frame workflow without knowing the presentation toolkit.

    Player and source adapters depend on this application boundary instead of
    importing ``LyricsState`` or constructing a concrete publisher. The
    composition root supplies the sole publisher implementation.
    """

    def __init__(
        self,
        publisher: DisplayPublisher,
        *,
        presenter: DisplayEngine,
        timeline: TimelineEngine,
    ) -> None:
        self._presenter = presenter
        self._publisher = publisher
        self._timeline = timeline
        self._document: LyricsDocument | None = None
        self._resolution = ResolutionState.NO_TRACK
        self._task: asyncio.Task[None] | None = None
        self._wake_event: asyncio.Event | None = None
        self._reported_task_failure: asyncio.Task[None] | None = None
        self._last_logged_display_key: tuple[object, ...] | None = None

    async def start(self) -> None:
        """Start the owned smooth-display task; repeated calls are harmless."""
        task = self._task
        if task is not None:
            if not task.done():
                return
            self._observe_task_failure(task)
        self._wake_event = asyncio.Event()
        task = create_owned_task(self._run(), name="kotonoha-display-clock")
        self._task = task
        task.add_done_callback(self._display_task_finished)

    async def stop(self) -> None:
        """Cancel and await the smooth-display task owned by this coordinator."""
        task = self._task
        self._task = None
        self._wake_event = None
        if task is None:
            return
        if task.done():
            # The done callback already reported any failure. Stopping a clock
            # that failed before shutdown remains an idempotent cleanup action.
            self._observe_task_failure(task)
            return
        task.cancel()
        cancellation_requested = await wait_for_owned(task)
        self._observe_task_failure(task)
        if cancellation_requested:
            raise asyncio.CancelledError

    def project(
        self,
        playback: PlaybackObservation,
        document: LyricsDocument | None,
    ) -> DisplayFrame:
        """Build an ordinary completed frame without publishing it."""
        resolution = ResolutionState.from_facts(playback, document)
        return self._presenter.project_observation(playback, document, resolution)

    def project_resolution(
        self,
        playback: PlaybackObservation,
        document: LyricsDocument | None,
        resolution: ResolutionState,
    ) -> DisplayFrame:
        """Build a frame from explicit resolution facts without publishing it."""
        return self._presenter.project_observation(playback, document, resolution)

    def set_options(self, options: DisplayOptions) -> None:
        """Replace display options and immediately reproject the active frame."""
        self._presenter.set_options(options)
        playback = self._timeline.advance()
        if playback is not None:
            self.publish_frame(self._project_observation(playback))

    def publish(
        self,
        playback: PlaybackObservation,
        document: LyricsDocument | None,
    ) -> DisplayFrame:
        """Project and publish one ordinary completed playback/document pair."""
        return self.publish_resolution(
            playback,
            document,
            ResolutionState.from_facts(playback, document),
        )

    def publish_resolution(
        self,
        playback: PlaybackObservation,
        document: LyricsDocument | None,
        resolution: ResolutionState,
    ) -> DisplayFrame:
        """Publish a playback/document pair with explicit source resolution."""
        self._document = document
        self._resolution = resolution
        playback = self._timeline.set_observation(playback)
        frame = self._project_observation(playback)
        self.publish_frame(frame)
        self._wake()
        return frame

    def publish_frame(self, frame: DisplayFrame) -> bool:
        """Publish an already projected frame through the sole Qt bridge."""
        self._log_display_source(frame)
        if frame.state is DisplayState.NO_TRACK and frame.track is None:
            self._document = None
            self._resolution = ResolutionState.NO_TRACK
            self._timeline.reset()
        return self._publisher.publish(frame)

    def tick(self, position_s: float | None, status: PlaybackStatus) -> None:
        """Apply a clock calibration and publish the resulting display frame."""
        playback = self._timeline.observe(position_s, status)
        if playback is None:
            return
        self.publish_frame(self._project_observation(playback))
        self._wake()

    def _project_observation(self, playback: PlaybackObservation) -> DisplayFrame:
        return self._presenter.project_observation(playback, self._document, self._resolution)

    async def _run(self) -> None:
        wake_event = self._wake_event
        if wake_event is None:
            return
        try:
            while True:
                playback = self._timeline.advance()
                if playback is not None:
                    self.publish_frame(self._project_observation(playback))
                wake_event.clear()
                if not self._timeline.playing:
                    await wake_event.wait()
                    continue
                try:
                    await asyncio.wait_for(wake_event.wait(), DISPLAY_TICK_INTERVAL_S)
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise

    def _display_task_finished(self, task: asyncio.Task[None]) -> None:
        """Observe a failed clock task even when no later shutdown occurs."""
        self._observe_task_failure(task)

    def _observe_task_failure(self, task: asyncio.Task[None]) -> None:
        """Read and report an unexpected task failure exactly once."""
        if task.cancelled() or self._reported_task_failure is task:
            return
        error = task.exception()
        if error is None:
            return
        self._reported_task_failure = task
        logger.error("Display clock task failed: %s", error)

    def _wake(self) -> None:
        if self._wake_event is not None:
            self._wake_event.set()

    def _log_display_source(self, frame: DisplayFrame) -> None:
        """Log one authoritative source record per displayed lyric document."""
        document = frame.document
        if document is None:
            self._last_logged_display_key = None
            return
        key = self._display_log_key(frame)
        previous = self._last_logged_display_key
        if previous == key:
            return
        self._last_logged_display_key = key

        track = frame.track
        lyric_source = document.source_name if document.source_name is not None else document.source_id
        playback_source = track.adapter_id if track is not None else "none"
        logger.info(
            "LYRICS DISPLAY ACTIVE: lyric_source=%r source_id=%r playback_source=%r "
            "state=%s track=%r artist=%r ref=%r song_id=%r timing=%s lines=%d duration=%s",
            lyric_source,
            document.source_id,
            playback_source,
            frame.state,
            track.title if track is not None else "",
            track.artist if track is not None else "",
            track.track_ref if track is not None else None,
            document.song_id,
            document.timing,
            len(document.lines),
            "-" if document.duration_s is None else f"{document.duration_s:.3f}s",
        )

    @staticmethod
    def _display_log_key(frame: DisplayFrame) -> tuple[object, ...]:
        """Return stable display facts that matter when diagnosing source changes."""
        track = frame.track
        document = frame.document
        if document is None:
            raise ValueError("display log key requires a lyric document")
        return (
            frame.state,
            track.adapter_id if track is not None else None,
            track.track_ref if track is not None else None,
            track.title if track is not None else "",
            track.artist if track is not None else "",
            document.source_id,
            document.source_name,
            document.song_id,
            document.timing,
            document.duration_s,
            len(document.lines),
        )


__all__ = ["DisplayCoordinator"]
