"""Versioned, source-neutral messages exchanged by external lyric adapters."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeAlias

from ..playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity
from .models import LyricLine, LyricsDocument, LyricsOrigin, LyricWord, TimingKind, validate_document

PROTOCOL_NAME = "kotonoha.adapter"
PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 4 * 1024 * 1024
MAX_LINES = 4096
MAX_WORDS_PER_LINE = 4096


class AdapterProtocolError(ValueError):
    """A wire message failed schema or lyric timing validation."""


@dataclass(frozen=True)
class AdapterSnapshot:
    """A complete adapter observation with an optional lyric document."""

    adapter_id: str
    sequence: int
    captured_at: str
    playback: PlaybackObservation
    document: LyricsDocument | None


@dataclass(frozen=True)
class AdapterClock:
    """A high-frequency clock update referring to the latest adapter track."""

    adapter_id: str
    sequence: int
    track_ref: str | None
    position_s: float | None
    status: PlaybackStatus
    observed_at: float


AdapterMessage: TypeAlias = AdapterSnapshot | AdapterClock


class AdapterProtocolDecoder:
    """Decode and validate versioned adapter messages at one external boundary.

    The limits are constructor dependencies so a receiver can own and test its
    resource policy without relying on module-level mutable state.
    """

    def __init__(
        self,
        *,
        max_message_bytes: int = MAX_MESSAGE_BYTES,
        max_lines: int = MAX_LINES,
        max_words_per_line: int = MAX_WORDS_PER_LINE,
    ) -> None:
        if max_message_bytes <= 0 or max_lines <= 0 or max_words_per_line <= 0:
            raise ValueError("adapter protocol limits must be positive")
        self._max_message_bytes = max_message_bytes
        self._max_lines = max_lines
        self._max_words_per_line = max_words_per_line

    @property
    def max_message_bytes(self) -> int:
        """Return the byte limit that transport adapters must enforce."""
        return self._max_message_bytes

    def decode_text(self, raw_text: str, *, observed_at: float) -> AdapterMessage:
        """Decode one UTF-8 JSON text frame under the configured size budget."""
        self.validate_text_size(raw_text)
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise AdapterProtocolError("adapter message is not valid JSON") from exc
        return self.decode(payload, observed_at=observed_at)

    def validate_text_size(self, raw_text: str) -> None:
        """Validate the encoded size of a text frame before any fallback parser runs."""
        try:
            message_size = len(raw_text.encode("utf-8"))
        except UnicodeEncodeError as exc:
            raise AdapterProtocolError("adapter message is not valid UTF-8 text") from exc
        if message_size > self._max_message_bytes:
            raise AdapterProtocolError("adapter message exceeds the byte limit")

    def decode(self, payload: object, *, observed_at: float) -> AdapterMessage:
        """Parse one versioned adapter payload into typed application input.

        The parser is intentionally strict at this boundary: a malformed
        document is rejected as a whole instead of becoming a plausible partial
        lyric result.
        """
        root = _mapping(payload, "adapter message")
        if root.get("protocol") != PROTOCOL_NAME:
            raise AdapterProtocolError("unsupported adapter protocol")
        version = root.get("version")
        if isinstance(version, bool) or not isinstance(version, int) or version != PROTOCOL_VERSION:
            raise AdapterProtocolError("unsupported adapter protocol version")
        message_type = root.get("type")
        adapter_id = _non_empty_string(root.get("adapter"), "adapter")
        sequence = _non_negative_int(root.get("sequence"), "sequence")
        captured_at = _non_empty_string(root.get("capturedAt"), "capturedAt")

        if message_type == "snapshot":
            playback = _parse_playback(root.get("playback"), adapter_id, observed_at)
            document = _parse_document(
                root.get("lyrics"),
                playback.track,
                max_lines=self._max_lines,
                max_words_per_line=self._max_words_per_line,
            )
            return AdapterSnapshot(adapter_id, sequence, captured_at, playback, document)
        if message_type == "clock":
            track_ref = _optional_string(root.get("trackRef"), "trackRef")
            position_s = _optional_number(root.get("positionS"), "positionS", minimum=0.0)
            status = PlaybackStatus.from_wire(root.get("status"))
            if status is None:
                raise AdapterProtocolError("clock has an unknown playback status")
            return AdapterClock(adapter_id, sequence, track_ref, position_s, status, observed_at)
        raise AdapterProtocolError("unknown adapter message type")


def parse_adapter_message(payload: object, *, observed_at: float) -> AdapterMessage:
    """Decode a payload with the default adapter protocol policy."""
    return AdapterProtocolDecoder().decode(payload, observed_at=observed_at)


def _parse_playback(value: object, adapter_id: str, observed_at: float) -> PlaybackObservation:
    raw = _mapping(value, "playback")
    player_id = _string(raw.get("playerId"), "playback.playerId")
    status = PlaybackStatus.from_wire(raw.get("status"))
    if status is None:
        raise AdapterProtocolError("playback has an unknown playback status")
    position_s = _optional_number(raw.get("positionS"), "playback.positionS", minimum=0.0)
    duration_s = _optional_number(raw.get("durationS"), "playback.durationS", minimum=0.0)
    track_value = raw.get("track")
    track = None if track_value is None else _parse_track(track_value, adapter_id, player_id, duration_s)
    return PlaybackObservation(adapter_id, player_id, track, status, position_s, duration_s, observed_at)


def _parse_track(value: object, adapter_id: str, player_id: str, duration_s: float | None) -> TrackIdentity:
    raw = _mapping(value, "playback.track")
    stable_id = _optional_string(raw.get("stableId"), "playback.track.stableId")
    title = _string(raw.get("title"), "playback.track.title")
    raw_title = _string(raw.get("rawTitle"), "playback.track.rawTitle")
    artist = _string(raw.get("artist"), "playback.track.artist")
    album = _string(raw.get("album"), "playback.track.album")
    url = _optional_string(raw.get("url"), "playback.track.url")
    track_duration = _optional_number(raw.get("durationS"), "playback.track.durationS", minimum=0.0)
    return TrackIdentity(
        adapter_id=adapter_id,
        player_id=player_id,
        stable_id=stable_id,
        title=title,
        raw_title=raw_title,
        artist=artist,
        album=album,
        url=url,
        duration_s=track_duration if track_duration is not None else duration_s,
    )


def _parse_document(
    value: object,
    track: TrackIdentity | None,
    *,
    max_lines: int,
    max_words_per_line: int,
) -> LyricsDocument | None:
    if value is None:
        return None
    raw = _mapping(value, "lyrics")
    source_id = _non_empty_string(raw.get("source"), "lyrics.source")
    source_name = _optional_string(raw.get("sourceName"), "lyrics.sourceName")
    song_id = _optional_string(raw.get("songId"), "lyrics.songId")
    timing_value = raw.get("timing")
    timing: TimingKind | None
    if timing_value is None:
        timing = None
    else:
        try:
            timing = TimingKind(_string(timing_value, "lyrics.timing"))
        except ValueError as exc:
            raise AdapterProtocolError("lyrics has an unknown timing kind") from exc
    language = _optional_string(raw.get("language"), "lyrics.language")
    title = _optional_string(raw.get("title"), "lyrics.title")
    artist = _optional_string(raw.get("artist"), "lyrics.artist")
    album = _optional_string(raw.get("album"), "lyrics.album")
    duration_s = _optional_number(raw.get("durationS"), "lyrics.durationS", minimum=0.0)
    lines_value = raw.get("lines", [])
    lines_raw = _list(lines_value, "lyrics.lines")
    if len(lines_raw) > max_lines:
        raise AdapterProtocolError("lyrics exceeds the line limit")
    lines = tuple(
        _parse_line(line, index, max_words_per_line=max_words_per_line)
        for index, line in enumerate(lines_raw)
    )
    document = LyricsDocument(
        source_id=source_id,
        source_name=source_name,
        song_id=song_id,
        timing=timing,
        language=language,
        title=title if title is not None else track.title if track is not None else None,
        artist=artist if artist is not None else track.artist if track is not None else None,
        album=album if album is not None else track.album if track is not None else None,
        duration_s=duration_s if duration_s is not None else track.duration_s if track is not None else None,
        lines=lines,
        origin=(
            LyricsOrigin.EMBEDDED
            if source_id == "embedded"
            else LyricsOrigin.SIDECAR
            if source_id == "sidecar"
            else LyricsOrigin.ADAPTER
        ),
    )
    if lines and document.timing is None:
        raise AdapterProtocolError("lyrics with lines must declare timing")
    try:
        validate_document(document)
    except ValueError as exc:
        raise AdapterProtocolError(str(exc)) from exc
    return document


def _parse_line(value: object, fallback_index: int, *, max_words_per_line: int) -> LyricLine:
    raw = _mapping(value, "lyrics line")
    index = _non_negative_int(raw.get("index", fallback_index), "lyrics line index")
    line_id = _string(raw.get("id", str(index)), "lyrics line id")
    start = _finite_number(raw.get("start"), "lyrics line start", minimum=0.0)
    end = _finite_number(raw.get("end"), "lyrics line end", minimum=start)
    text = _string(raw.get("text"), "lyrics line text")
    translation = _string(raw.get("translation", ""), "lyrics line translation")
    words_value = raw.get("words", [])
    words_raw = _list(words_value, "lyrics line words")
    if len(words_raw) > max_words_per_line:
        raise AdapterProtocolError("lyrics line exceeds the word limit")
    words = tuple(_parse_word(word) for word in words_raw)
    return LyricLine(index, line_id, start, end, text, translation, words)


def _parse_word(value: object) -> LyricWord:
    raw = _mapping(value, "lyrics word")
    start = _optional_number(raw.get("start"), "lyrics word start", minimum=0.0)
    end = _optional_number(raw.get("end"), "lyrics word end", minimum=start if start is not None else None)
    if (start is None) != (end is None):
        raise AdapterProtocolError("lyrics word has a partial timing span")
    return LyricWord(start, end, _string(raw.get("text"), "lyrics word text"))


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise AdapterProtocolError(f"{name} is not an object")
    return value


def _list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise AdapterProtocolError(f"{name} is not an array")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise AdapterProtocolError(f"{name} is not a string")
    return value


def _non_empty_string(value: object, name: str) -> str:
    parsed = _string(value, name)
    if not parsed:
        raise AdapterProtocolError(f"{name} is empty")
    return parsed


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _string(value, name)


def _non_negative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AdapterProtocolError(f"{name} is not a non-negative integer")
    return value


def _finite_number(value: object, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdapterProtocolError(f"{name} is not a number")
    parsed = float(value)
    if not math.isfinite(parsed) or minimum is not None and parsed < minimum:
        raise AdapterProtocolError(f"{name} is outside its allowed range")
    return parsed


def _optional_number(value: object, name: str, *, minimum: float | None = None) -> float | None:
    if value is None:
        return None
    return _finite_number(value, name, minimum=minimum)
