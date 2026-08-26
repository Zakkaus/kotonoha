import pytest

pytest.importorskip("PyQt6.QtCore")

from kotonoha.display.models import DisplayFrame, DisplayState  # noqa: E402
from kotonoha.playback.models import TrackIdentity  # noqa: E402
from kotonoha.state import LyricsState  # noqa: E402


def frame(title: str = "", current_time: float | None = None) -> DisplayFrame:
    track = TrackIdentity("test", "player", title=title) if title else None
    state = DisplayState.LYRICS_NOT_FOUND if track is not None else DisplayState.NO_TRACK
    return DisplayFrame(state, track, current_time=current_time)


def _collect(state):
    received = []
    state.frame_changed.connect(received.append)
    return received


def test_update_emits_on_change():
    state = LyricsState()
    received = _collect(state)

    changed = state.update(frame("A"))

    assert changed is True
    assert len(received) == 1
    assert received[0].track is not None
    assert received[0].track.title == "A"
    assert state.frame.track is not None
    assert state.frame.track.title == "A"


def test_update_does_not_emit_on_identical_snapshot():
    state = LyricsState()
    received = _collect(state)

    snap = frame("A", 1.0)
    assert state.update(snap) is True
    assert state.update(frame("A", 1.0)) is False

    assert len(received) == 1


def test_heartbeat_with_advanced_time_emits():
    state = LyricsState()
    received = _collect(state)

    state.update(frame("A", 1.0))
    state.update(frame("A", 1.5))

    assert len(received) == 2


def test_clear_resets_to_empty():
    state = LyricsState()
    state.update(frame("A"))
    assert state.clear() is True
    assert state.frame.state is DisplayState.NO_TRACK
