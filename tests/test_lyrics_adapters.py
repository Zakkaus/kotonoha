from kotonoha.display.models import DisplayState, ResolutionState
from kotonoha.display.presentation import DisplayEngine
from kotonoha.lyrics.adapter import LyricsDocumentAdapter
from kotonoha.lyrics.models import LyricLine
from kotonoha.playback.models import PlaybackObservation, PlaybackStatus
from kotonoha.providers.mpris_adapter import MprisPlaybackAdapter
from kotonoha.providers.mpris_track import TrackInfo


def _line(index: int, start: float, end: float, text: str) -> LyricLine:
    return LyricLine(index, f"L{index}", start, end, text, "")


def test_mpris_adapter_preserves_raw_identity_alongside_lookup_fields():
    info = TrackInfo(
        title="Song",
        artist="Artist",
        album="Album",
        length_s=180.0,
        track_id="/track/1",
        reported_title="(3) Artist - Song - YouTube",
        url="https://player.example/song",
    )

    observation = MprisPlaybackAdapter().observe(
        info,
        player_name="org.mpris.MediaPlayer2.browser",
        status="Playing",
        position_s=4.0,
        observed_at=12.0,
    )

    assert observation.status is PlaybackStatus.PLAYING
    assert observation.track is not None
    assert observation.track.title == "Song"
    assert observation.track.raw_title == "(3) Artist - Song - YouTube"
    assert observation.track.track_ref == "mpris:org.mpris.MediaPlayer2.browser:/track/1"


def test_document_and_presentation_adapters_share_the_same_canonical_path():
    document = LyricsDocumentAdapter().adapt(
        [_line(0, 0.0, 5.0, "hello"), _line(1, 5.0, 10.0, "world")],
        source_id="sidecar",
        title="Song",
        artist="Artist",
        duration_s=180.0,
    )

    playback = PlaybackObservation("test", "player", None, PlaybackStatus.PLAYING, 6.0, 180.0, 0.0)
    frame = DisplayEngine().project_observation(playback, document, ResolutionState.AVAILABLE)

    assert document.source_id == "sidecar"
    assert frame.state is DisplayState.LYRICS_AVAILABLE
    assert frame.current is not None and frame.current.text == "world"
    assert frame.document is document
