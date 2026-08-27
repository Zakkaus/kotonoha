import asyncio
import logging

from kotonoha.display.coordinator import DisplayCoordinator
from kotonoha.display.timeline import TimelineEngine
from kotonoha.playback.models import PlaybackObservation
from kotonoha.state import LyricsState


class _FailingTimeline(TimelineEngine):
    def advance(self) -> PlaybackObservation | None:
        raise RuntimeError("timeline failed")


async def test_display_stop_observes_a_completed_clock_task_failure(caplog):
    coordinator = DisplayCoordinator(LyricsState(), timeline=_FailingTimeline())

    with caplog.at_level(logging.ERROR):
        await coordinator.start()
        await asyncio.sleep(0)
        await coordinator.stop()

    assert "Display clock task failed: timeline failed" in caplog.text
