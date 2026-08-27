"""Application-owned display projection and Qt compatibility publishing."""

from __future__ import annotations

import asyncio
import logging

from ..lyrics.models import LyricsDocument
from ..playback.models import PlaybackObservation, PlaybackStatus
from ..state import LyricsState
from .models import DisplayFrame, DisplayOptions, DisplayState, ResolutionState
from .presentation import DisplayEngine
from .publisher import QtDisplayPublisher
from .timeline import TimelineEngine

DISPLAY_TICK_INTERVAL_S = 1.0 / 60.0
logger = logging.getLogger(__name__)


class DisplayCoordinator:
    """Own the single normalized-frame path into the presentation state.

    Player and source adapters depend on this application boundary instead of
    importing ``LyricsState``, constructing a publisher, or deciding how a
    document becomes a display frame. The coordinator itself is created once by
    the composition root and owns the compatibility write for the Qt UI.
    """

    def __init__(
        self,
        state: LyricsState,
        *,
        presenter: DisplayEngine | None = None,
        timeline: TimelineEngine | None = None,
        options: DisplayOptions | None = None,
    ) -> None:
        self._presenter = presenter if presenter is not None else DisplayEngine(options)
        self._publisher = QtDisplayPublisher(state)
        self._timeline = timeline if timeline is not None else TimelineEngine()
        self._document: LyricsDocument | None = None
        self._resolution = ResolutionState.NO_TRACK
        self._task: asyncio.Task[None] | None = None
        self._wake_event: asyncio.Event | None = None
        self._reported_task_failure: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the owned smooth-display task; repeated calls are harmless."""
        task = self._task
        if task is not None:
            if not task.done():
                return
            self._observe_task_failure(task)
        self._wake_event = asyncio.Event()
        task = asyncio.create_task(self._run(), name="kotonoha-display-clock")
        self._task = task
        task.add_done_callback(self._display_task_finished)

    async def stop(self) -> None:
        """Cancel and await the smooth-display task owned by this coordinator."""
        task = self._task
        self._task = None
        self._wake_event = None
        if task is None:
            return
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            finally:
                self._observe_task_failure(task)
            return
        self._observe_task_failure(task)

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


__all__ = ["DisplayCoordinator"]
