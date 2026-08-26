import pytest

from kotonoha.display.models import EMPTY_FRAME, DisplayFrame, DisplayState
from kotonoha.lyrics.models import LyricLine, LyricsDocument, TimingKind, validate_document
from kotonoha.playback.models import TrackIdentity


def test_empty_display_frame_represents_no_track():
    assert EMPTY_FRAME.state is DisplayState.NO_TRACK
    assert EMPTY_FRAME.track is None
    assert EMPTY_FRAME.document is None


def test_canonical_document_keeps_source_and_timing_explicit():
    line = LyricLine(0, "L0", 0.0, 2.0, "hello", "")
    document = LyricsDocument("sidecar", timing=TimingKind.LINE, lines=(line,))

    validate_document(document)

    frame = DisplayFrame(
        DisplayState.LYRICS_AVAILABLE,
        TrackIdentity("mpris", "player", title="Song", artist="Artist"),
        document,
        current=line,
    )
    assert frame.document is document
    assert frame.document.source_id == "sidecar"


def test_document_rejects_invalid_line_order():
    document = LyricsDocument(
        "test",
        timing=TimingKind.LINE,
        lines=(
            LyricLine(0, "0", 2.0, 3.0, "later", ""),
            LyricLine(1, "1", 1.0, 2.0, "earlier", ""),
        ),
    )

    with pytest.raises(ValueError, match="not ordered"):
        validate_document(document)
