import pytest

from kotonoha.display.models import (
    DisplayInput,
    DisplayOptions,
    DisplayScript,
    DisplayState,
    InterludeCountdown,
    InterludeMarkerStyle,
    ResolutionState,
)
from kotonoha.display.offsets import track_offset_key
from kotonoha.display.presentation import DisplayEngine
from kotonoha.lyrics.models import LyricLine, LyricsDocument, LyricWord, TimingKind
from kotonoha.playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity


def _track() -> TrackIdentity:
    return TrackIdentity("test", "player", stable_id="song", title="Song", artist="Artist")


def _observation(position: float | None, status: PlaybackStatus = PlaybackStatus.PLAYING) -> PlaybackObservation:
    return PlaybackObservation("test", "player", _track(), status, position, 180.0, 1.0)


def _document(lines: tuple[LyricLine, ...], *, duration_s: float | None = 180.0) -> LyricsDocument:
    timing = TimingKind.WORD if any(line.words for line in lines) else TimingKind.LINE
    return LyricsDocument("test", timing=timing, duration_s=duration_s, lines=lines)


def test_display_engine_preserves_explicit_resolution_states():
    engine = DisplayEngine()

    resolving = engine.project_observation(_observation(0.0), None, ResolutionState.RESOLVING)
    not_found = engine.project_observation(_observation(0.0), None, ResolutionState.NOT_FOUND)
    no_track = engine.project_observation(
        PlaybackObservation("test", "player", None, PlaybackStatus.STOPPED, None, None, 1.0),
        None,
        ResolutionState.NO_TRACK,
    )

    assert resolving.state is DisplayState.RESOLVING
    assert not_found.state is DisplayState.LYRICS_NOT_FOUND
    assert no_track.state is DisplayState.NO_TRACK


def test_display_input_rejects_contradictory_resolution_facts():
    options = DisplayOptions()
    stopped_without_track = PlaybackObservation("test", "player", None, PlaybackStatus.STOPPED, None, None, 1.0)
    document = _document((LyricLine(0, "line", 0.0, 1.0, "line", ""),))

    with pytest.raises(ValueError, match="requires a lyric document"):
        DisplayInput(_observation(0.0), None, ResolutionState.AVAILABLE, options)
    with pytest.raises(ValueError, match="requires a playback track"):
        DisplayInput(stopped_without_track, None, ResolutionState.RESOLVING, options)
    with pytest.raises(ValueError, match="cannot contain playback or lyric data"):
        DisplayInput(stopped_without_track, document, ResolutionState.NO_TRACK, options)


def test_display_engine_preserves_pause_and_reports_empty_available_documents():
    engine = DisplayEngine()
    empty_document = LyricsDocument("test", timing=TimingKind.LINE, lines=())

    paused = engine.project_observation(
        _observation(1.0, PlaybackStatus.PAUSED),
        empty_document,
        ResolutionState.AVAILABLE,
    )

    assert paused.is_playing is False
    assert paused.state is DisplayState.LYRICS_NOT_FOUND
    assert paused.diagnostic is not None
    assert paused.diagnostic.code == "empty_document"


def test_display_engine_projects_no_track_without_a_legacy_projection():
    frame = DisplayEngine().project_observation(
        PlaybackObservation("test", "player", None, PlaybackStatus.STOPPED, None, None, 1.0),
        None,
        ResolutionState.NO_TRACK,
    )

    assert frame.state is DisplayState.NO_TRACK
    assert frame.document is None


def test_display_engine_returns_progress_without_mutating_canonical_word_line():
    text = "我曾经"
    words = tuple(LyricWord(index * 0.5, (index + 1) * 0.5, character) for index, character in enumerate(text))
    line = LyricLine(0, "line", 0.0, 5.0, text, "", words)
    document = _document((line,))

    frame = DisplayEngine().project_observation(_observation(1.25), document, ResolutionState.AVAILABLE)

    assert frame.current is line
    assert frame.current.end == 5.0
    assert frame.word_progress is not None
    assert frame.word_progress.line_id == "line"
    assert frame.word_progress.fractions == (1.0, 1.0, 0.5)
    assert frame.word_progress.active_index == 2


def test_display_engine_returns_interlude_marker_and_semantic_progress():
    lines = (
        LyricLine(0, "lead", 0.0, 5.0, "lead", ""),
        LyricLine(1, "before", 5.0, 10.0, "before", ""),
        LyricLine(2, "after", 30.0, 35.0, "after", ""),
        LyricLine(3, "tail", 35.0, 40.0, "tail", ""),
        LyricLine(4, "end", 40.0, 45.0, "end", ""),
    )
    frame = DisplayEngine(
        DisplayOptions(
            interlude_style=InterludeMarkerStyle.SYMBOL,
            interlude_countdown=InterludeCountdown.SECONDS,
        )
    ).project_observation(_observation(20.0), _document(lines), ResolutionState.AVAILABLE)

    assert frame.state is DisplayState.LYRICS_AVAILABLE
    assert frame.current is None
    assert frame.interlude is not None
    assert frame.interlude_line is not None
    assert frame.interlude_line.text == "♪\u2003\u200310s"
    assert frame.line_progress is not None
    assert frame.line_progress.line_id == "interlude"
    assert frame.line_progress.fraction == 0.5


def test_display_engine_applies_options_at_the_display_boundary():
    line = LyricLine(0, "line", 1.0, 5.0, "简体", "翻译")
    document = LyricsDocument("test", title="Song", artist="Artist", timing=TimingKind.LINE, lines=(line,))
    key = track_offset_key(_track(), document)
    assert key is not None
    options = DisplayOptions(
        lead_ms=100,
        track_offsets_ms={key: 50},
        lyrics_script=DisplayScript.ZH_HANT,
    )

    frame = DisplayEngine().project_input(
        DisplayInput(_observation(1.0), document, ResolutionState.AVAILABLE, options)
    )

    assert frame.current_time == 1.15
    assert frame.track_offset_key == key
    assert frame.current is not None
    assert frame.current.text == "簡體"
    assert frame.current.translation == "翻譯"
