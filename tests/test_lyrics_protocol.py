import json
from typing import cast

import pytest

from kotonoha.lyrics.models import LyricsOrigin
from kotonoha.lyrics.protocol import (
    AdapterClock,
    AdapterProtocolDecoder,
    AdapterProtocolError,
    AdapterSnapshot,
)
from kotonoha.playback.models import PlaybackStatus


def _snapshot_payload() -> dict[str, object]:
    return {
        "protocol": "kotonoha.adapter",
        "version": 1,
        "type": "snapshot",
        "adapter": "future-player",
        "sequence": 7,
        "capturedAt": "2026-08-25T00:00:00Z",
        "playback": {
            "playerId": "player-1",
            "status": "Playing",
            "positionS": 3.5,
            "durationS": 180.0,
            "track": {
                "stableId": "song-1",
                "title": "Song",
                "rawTitle": "Song (Official)",
                "artist": "Artist",
                "album": "Album",
                "url": "https://player.example/song-1",
                "durationS": 180.0,
            },
        },
        "lyrics": {
            "source": "embedded",
            "songId": "song-1",
            "timing": "Word",
            "language": "en",
            "lines": [
                {
                    "index": 0,
                    "id": "line-0",
                    "start": 1.0,
                    "end": 4.0,
                    "text": "hello",
                    "translation": "你好",
                    "words": [{"start": 1.0, "end": 2.0, "text": "hello"}],
                }
            ],
        },
    }


def test_decoder_normalizes_snapshot_without_display_projection_fields():
    payload = _snapshot_payload()
    message = AdapterProtocolDecoder().decode(payload, observed_at=12.0)

    assert isinstance(message, AdapterSnapshot)
    assert message.playback.status is PlaybackStatus.PLAYING
    assert message.playback.track is not None
    assert message.playback.track.raw_title == "Song (Official)"
    assert message.document is not None
    assert message.document.source_id == "embedded"
    assert message.document.origin is LyricsOrigin.EMBEDDED
    assert message.document.lines[0].words[0].text == "hello"


def test_decoder_accepts_a_clock_as_a_distinct_message_kind():
    payload = {
        "protocol": "kotonoha.adapter",
        "version": 1,
        "type": "clock",
        "adapter": "future-player",
        "sequence": 8,
        "capturedAt": "2026-08-25T00:00:01Z",
        "trackRef": "future-player:player-1:song-1",
        "positionS": 4.0,
        "status": "Paused",
    }

    message = AdapterProtocolDecoder().decode(payload, observed_at=13.0)

    assert isinstance(message, AdapterClock)
    assert message.track_ref == "future-player:player-1:song-1"
    assert message.position_s == 4.0
    assert message.status is PlaybackStatus.PAUSED


def test_decoder_rejects_the_removed_legacy_cider_payload():
    legacy = {
        "source": "kotonoha-cider-lyrics",
        "lyrics": {"found": True, "provider": "Apple Music"},
        "playback": {"isPlaying": True},
    }

    with pytest.raises(AdapterProtocolError, match="unsupported adapter protocol"):
        AdapterProtocolDecoder().decode(legacy, observed_at=1.0)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(version=2),
        lambda payload: payload["lyrics"]["lines"][0].update(end=0.5),
        lambda payload: payload["lyrics"]["lines"][0]["words"][0].update(end=None),
        lambda payload: payload["playback"].update(positionS=float("nan")),
    ],
)
def test_decoder_rejects_invalid_contract_values(mutate):
    payload = _snapshot_payload()
    mutate(payload)

    with pytest.raises(AdapterProtocolError):
        AdapterProtocolDecoder().decode(payload, observed_at=12.0)


def test_decoder_enforces_message_and_collection_budgets():
    payload = _snapshot_payload()
    text = json.dumps(payload)
    with pytest.raises(AdapterProtocolError, match="byte limit"):
        AdapterProtocolDecoder(max_message_bytes=len(text.encode()) - 1).decode_text(text, observed_at=1.0)

    lyrics = cast(dict[str, object], payload["lyrics"])
    lines = cast(list[dict[str, object]], lyrics["lines"])
    lines.append(dict(lines[0]))
    with pytest.raises(AdapterProtocolError, match="line limit"):
        AdapterProtocolDecoder(max_lines=1).decode(payload, observed_at=1.0)
