import time

from kotonoha.lyrics.models import LyricLine
from kotonoha.providers.mpris_timeline import MprisPositionCalibrator
from kotonoha.providers.mpris_track import TrackCommit, TrackInfo


def _commit(*, generation: int = 1, start_position: float | None = None) -> TrackCommit:
    return TrackCommit(
        generation=generation,
        player_name="org.mpris.MediaPlayer2.test",
        info=TrackInfo("Song", "Artist", "Album", 180.0, "/track/1"),
        start_position=start_position,
    )


def test_timeline_calibrates_a_stale_transition_offset():
    timeline = MprisPositionCalibrator()
    commit = _commit(start_position=500.0)

    timeline.observe_commit(commit)

    assert timeline.offset == 500.0
    assert timeline.calibrate(commit, 1.0, time.monotonic()) is True
    assert timeline.offset == 0.0


def test_timeline_reconciles_a_cumulative_player_position_after_resolution():
    timeline = MprisPositionCalibrator()
    commit = _commit()
    lines = (
        LyricLine(0, "line-0", 0.0, 10.0, "first", ""),
        LyricLine(1, "line-1", 160.0, 170.0, "last", ""),
    )

    timeline.reconcile(commit, lines, song_length=172.0, raw_position=500.0)

    assert timeline.offset == 8.0


def test_timeline_reset_clears_offset_and_calibration_state():
    timeline = MprisPositionCalibrator()
    timeline.observe_commit(_commit(start_position=500.0))

    timeline.reset()

    assert timeline.offset == 0.0
    assert timeline.calibrate(_commit(start_position=500.0), 1.0, time.monotonic()) is False
