"""Application-owned display projection and Qt compatibility publishing."""

from __future__ import annotations

import asyncio
import contextlib

from ..lyrics.models import LyricsDocument
from ..playback.models import PlaybackObservation
from ..state import LyricsState
from .models import DisplayFrame, DisplayState
from .presentation import LyricsPresentationAdapter
from .publisher import QtDisplayPublisher
from .timeline import TimelineEngine

DISPLAY_TICK_INTERVAL_S = 1.0 / 60.0


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
        presenter: LyricsPresentationAdapter | None = None,
        timeline: TimelineEngine | None = None,
    ) -> None:
        self._presenter = presenter if presenter is not None else LyricsPresentationAdapter()
        self._publisher = QtDisplayPublisher(state)
        self._timeline = timeline if timeline is not None else TimelineEngine()
        self._document: LyricsDocument | None = None
        self._display_state: DisplayState | None = None
        self._task: asyncio.Task[None] | None = None
        self._wake_event: asyncio.Event | None = None

    async def start(self) -> None:
        """Start the owned smooth-display task; repeated calls are harmless."""
        if self._task is not None and not self._task.done():
            return
        self._wake_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="kotonoha-display-clock")

    async def stop(self) -> None:
        """Cancel and await the smooth-display task owned by this coordinator."""
        task = self._task
        self._task = None
        self._wake_event = None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def project(
        self,
        playback: PlaybackObservation,
        document: LyricsDocument | None,
        *,
        state: DisplayState | None = None,
    ) -> DisplayFrame:
        """Build a frame without publishing it."""
        return self._presenter.project_observation(playback, document, state=state)

    def publish(
        self,
        playback: PlaybackObservation,
        document: LyricsDocument | None,
        *,
        state: DisplayState | None = None,
    ) -> DisplayFrame:
        """Project and publish one normalized playback/document pair."""
        self._document = document
        self._display_state = state
        playback = self._timeline.set_observation(playback)
        frame = self._project_observation(playback)
        self.publish_frame(frame)
        self._wake()
        return frame

    def publish_frame(self, frame: DisplayFrame) -> bool:
        """Publish an already projected frame through the sole Qt bridge."""
        if frame.state is DisplayState.NO_TRACK and frame.track is None:
            self._document = None
            self._display_state = None
            self._timeline.reset()
        return self._publisher.publish(frame)

    def tick(self, position_s: float | None, is_playing: bool | None) -> None:
        """Apply a clock calibration and publish the resulting display frame."""
        playback = self._timeline.observe(position_s, is_playing)
        if playback is None:
            return
        self.publish_frame(self._project_observation(playback))
        self._wake()

    def _project_observation(self, playback: PlaybackObservation) -> DisplayFrame:
        return self.project(playback, self._document, state=self._display_state)

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

    def _wake(self) -> None:
        if self._wake_event is not None:
            self._wake_event.set()


__all__ = ["DisplayCoordinator"]
