import asyncio
import logging

from kotonoha.clock import MediaClock
from kotonoha.display.coordinator import DisplayCoordinator
from kotonoha.display.models import ResolutionState
from kotonoha.display.timeline import TimelineEngine
from kotonoha.lyrics.models import LyricLine, LyricsDocument, TimingKind
from kotonoha.playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity
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


class _FakeMonotonic:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


def test_display_tick_does_not_revert_to_a_lagging_polled_line():
    monotonic = _FakeMonotonic()
    timeline = TimelineEngine(MediaClock(monotonic=monotonic))
    state = LyricsState()
    coordinator = DisplayCoordinator(state, timeline=timeline)
    track = TrackIdentity("test", "player", stable_id="song", title="Song", artist="Artist")
    playback = PlaybackObservation("test", "player", track, PlaybackStatus.PLAYING, 4.8, 10.0, 100.0)
    document = LyricsDocument(
        "test",
        timing=TimingKind.LINE,
        duration_s=10.0,
        lines=(
            LyricLine(0, "line-0", 0.0, 5.0, "first", ""),
            LyricLine(1, "line-1", 5.0, 10.0, "second", ""),
        ),
    )

    coordinator.publish_resolution(playback, document, ResolutionState.AVAILABLE)
    monotonic.value = 100.3
    coordinator.tick(5.0, PlaybackStatus.PLAYING)
    assert state.frame.current is not None
    assert state.frame.current.id == "line-1"

    # A coarse player sample can lag the smooth clock just after the boundary.
    monotonic.value = 100.4
    coordinator.tick(4.9, PlaybackStatus.PLAYING)

    assert state.frame.current is not None
    assert state.frame.current.id == "line-1"


def test_display_logs_provider_metadata_once_per_document_and_resets_after_clear(caplog):
    state = LyricsState()
    coordinator = DisplayCoordinator(state)
    track = TrackIdentity("test", "player", stable_id="song", title="Song", artist="Artist")
    playback = PlaybackObservation("test", "player", track, PlaybackStatus.PLAYING, 1.0, 10.0, 100.0)
    first_document = LyricsDocument(
        "lrclib",
        source_name="LRCLIB",
        song_id="song-1",
        timing=TimingKind.LINE,
        duration_s=10.0,
        lines=(
            LyricLine(0, "line-0", 0.0, 5.0, "first", ""),
            LyricLine(1, "line-1", 5.0, 10.0, "second", ""),
        ),
    )
    second_document = LyricsDocument(
        "netease",
        source_name="Netease",
        song_id="song-1",
        timing=TimingKind.LINE,
        duration_s=10.0,
        lines=first_document.lines,
    )

    with caplog.at_level(logging.DEBUG):
        coordinator.publish_resolution(playback, first_document, ResolutionState.AVAILABLE)
        coordinator.tick(2.0, PlaybackStatus.PLAYING)
        coordinator.tick(6.0, PlaybackStatus.PLAYING)
        coordinator.publish_resolution(playback, first_document, ResolutionState.AVAILABLE)
        coordinator.publish_resolution(playback, second_document, ResolutionState.AVAILABLE)
        coordinator.publish_resolution(playback, None, ResolutionState.NOT_FOUND)
        coordinator.publish_resolution(playback, first_document, ResolutionState.AVAILABLE)

    messages = [record.getMessage() for record in caplog.records]
    metadata = [message for message in messages if "display lyric metadata" in message]
    assert len(metadata) == 3
    assert sum("provider='lrclib'" in message for message in metadata) == 2
    assert any("provider='netease'" in message and "lines=2" in message for message in metadata)
    assert all("display lyric line changed" not in message for message in messages)
