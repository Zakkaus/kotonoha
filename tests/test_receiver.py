import json

import pytest
from aiohttp import WSServerHandshakeError, web

pytest.importorskip("PyQt6.QtCore")
pytest.importorskip("aiohttp")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from kotonoha.display.coordinator import DisplayCoordinator  # noqa: E402
from kotonoha.display.models import DisplayState  # noqa: E402
from kotonoha.lyrics.match import TrackMetadata  # noqa: E402
from kotonoha.lyrics.ownership import SourceOwnershipCoordinator  # noqa: E402
from kotonoha.receiver import WS_PATH, AdapterReceiver  # noqa: E402
from kotonoha.state import LyricsState  # noqa: E402

FRAME = {
    "protocol": "kotonoha.adapter",
    "version": 1,
    "type": "snapshot",
    "adapter": "cider",
    "sequence": 1,
    "capturedAt": "2026-08-25T00:00:00Z",
    "playback": {
        "playerId": "cider",
        "status": "Playing",
        "positionS": 3.0,
        "durationS": 180.0,
        "track": {
            "stableId": "song-1",
            "title": "Song",
            "rawTitle": "Song",
            "artist": "X",
            "album": "Album",
            "url": None,
            "durationS": 180.0,
        },
    },
    "lyrics": {
        "source": "apple-music",
        "songId": "song-1",
        "timing": "Word",
        "language": "en",
        "title": "Song",
        "artist": "X",
        "album": "Album",
        "durationS": 180.0,
        "lines": [
            {"index": 1, "id": "L1", "start": 2.0, "end": 4.0, "text": "hello", "translation": "hi", "words": []}
        ],
    },
}

CLOCK = {
    "protocol": "kotonoha.adapter",
    "version": 1,
    "type": "clock",
    "adapter": "cider",
    "sequence": 2,
    "capturedAt": "2026-08-25T00:00:00Z",
    "trackRef": "cider:cider:song-1",
    "positionS": 12.5,
    "status": "Playing",
}


async def _client(state, **kwargs):
    ownership = kwargs.pop("ownership", SourceOwnershipCoordinator())
    receiver = AdapterReceiver(DisplayCoordinator(state), ownership=ownership, **kwargs)
    server = TestServer(receiver.build_app())
    client = TestClient(server)
    await client.start_server()
    return client, receiver


async def test_websocket_frame_updates_canonical_state():
    state = LyricsState()
    frames = []
    state.frame_changed.connect(frames.append)
    client, _ = await _client(state)
    try:
        ws = await client.ws_connect(WS_PATH)
        await ws.send_str(json.dumps(FRAME))
        await ws.close()
    finally:
        await client.close()

    published = next(frame for frame in frames if frame.state is DisplayState.LYRICS_AVAILABLE)
    assert published.track is not None
    assert published.track.title == "Song"
    assert published.current is not None
    assert published.current.text == "hello"
    assert state.frame.state is DisplayState.NO_TRACK


async def test_clock_message_updates_the_canonical_frame():
    state = LyricsState()
    frames = []
    state.frame_changed.connect(frames.append)
    client, _ = await _client(state)
    try:
        ws = await client.ws_connect(WS_PATH)
        await ws.send_str(json.dumps(FRAME))
        await ws.send_str(json.dumps(CLOCK))
        await ws.send_str(json.dumps({**CLOCK, "sequence": 3, "positionS": 13.0, "status": "Paused"}))
        await ws.close()
    finally:
        await client.close()

    updated = next(frame for frame in reversed(frames) if frame.current_time == 13.0)
    assert updated.state is DisplayState.LYRICS_AVAILABLE
    assert updated.is_playing is False
    assert state.frame.state is DisplayState.NO_TRACK


def test_clock_before_snapshot_is_rejected():
    state = LyricsState()
    receiver = AdapterReceiver(DisplayCoordinator(state), ownership=SourceOwnershipCoordinator())

    assert receiver.ingest(json.dumps(CLOCK), client_id=20) is False
    assert state.frame.state is DisplayState.NO_TRACK


def test_stale_snapshot_does_not_replace_the_latest_frame():
    state = LyricsState()
    receiver = AdapterReceiver(DisplayCoordinator(state), ownership=SourceOwnershipCoordinator())

    assert receiver.ingest(json.dumps(FRAME), client_id=21) is True
    playback = FRAME["playback"]
    if not isinstance(playback, dict):
        raise TypeError("test frame playback must be an object")
    stale = {
        **FRAME,
        "playback": {**playback, "positionS": 99.0},
    }

    assert receiver.ingest(json.dumps(stale), client_id=21) is False
    assert state.frame.current_time == 3.0


def test_clock_for_another_track_is_rejected_without_consuming_sequence():
    state = LyricsState()
    receiver = AdapterReceiver(DisplayCoordinator(state), ownership=SourceOwnershipCoordinator())

    assert receiver.ingest(json.dumps(FRAME), client_id=22) is True
    wrong_track = {**CLOCK, "trackRef": "cider:cider:other-song"}
    assert receiver.ingest(json.dumps(wrong_track), client_id=22) is False
    assert receiver.ingest(json.dumps({**CLOCK, "sequence": 2}), client_id=22) is True

    assert state.frame.current_time == 12.5
    assert state.frame.is_playing is True


async def test_post_debug_bypass_updates_state():
    state = LyricsState()
    client, _ = await _client(state)
    try:
        response = await client.post(WS_PATH, data=json.dumps(FRAME))
        assert response.status == 204
    finally:
        await client.close()

    assert state.frame.track is not None
    assert state.frame.track.title == "Song"


async def test_stop_clears_post_session_and_resets_its_sequence_namespace():
    state = LyricsState()
    ownership = SourceOwnershipCoordinator()
    receiver = AdapterReceiver(DisplayCoordinator(state), ownership=ownership)

    assert receiver.ingest(json.dumps(FRAME), client_id=0) is True
    assert ownership.current_match(TrackMetadata("Song", "X")) is not None
    assert state.frame.state is DisplayState.LYRICS_AVAILABLE

    await receiver.stop()

    assert ownership.current_match(TrackMetadata("Song", "X")) is None
    assert state.frame.state is DisplayState.NO_TRACK
    assert receiver.ingest(json.dumps(FRAME), client_id=0) is True


async def test_post_malformed_frame_returns_400():
    state = LyricsState()
    client, _ = await _client(state)
    try:
        response = await client.post(WS_PATH, data="not json{")
        assert response.status == 400
    finally:
        await client.close()

    assert state.frame.state is DisplayState.NO_TRACK


def test_build_app_registers_generic_adapter_route():
    app = AdapterReceiver(
        DisplayCoordinator(LyricsState()), ownership=SourceOwnershipCoordinator()
    ).build_app()
    assert any(getattr(route.resource, "canonical", "") == WS_PATH for route in app.router.routes())


async def test_start_bind_failure_resets_runner_and_reraises(monkeypatch):
    async def boom(_site):
        raise OSError(98, "Address already in use")

    monkeypatch.setattr(web.TCPSite, "start", boom)
    receiver = AdapterReceiver(DisplayCoordinator(LyricsState()), ownership=SourceOwnershipCoordinator())

    with pytest.raises(OSError):
        await receiver.start()

    assert receiver._runner is None


def test_closed_gate_retains_tick_without_publishing_external_content():
    state = LyricsState()
    gate = SourceOwnershipCoordinator()
    gate.select_external()
    receiver = AdapterReceiver(DisplayCoordinator(state), ownership=gate)

    assert receiver.ingest(json.dumps(FRAME), client_id=10) is True
    assert receiver.ingest(json.dumps({**CLOCK, "positionS": 3.0}), client_id=10)
    assert state.frame.state is DisplayState.NO_TRACK
    assert gate.current_match(TrackMetadata("Song", "X")) is not None
    timing = gate.current_timing(TrackMetadata("Song", "X"))
    assert timing is not None
    assert timing.current_time == 3.0


async def test_a_web_page_cannot_drive_the_overlay():
    state = LyricsState()
    receiver = AdapterReceiver(DisplayCoordinator(state), ownership=SourceOwnershipCoordinator())
    async with TestClient(TestServer(receiver.build_app())) as client:
        blocked = await client.post(
            WS_PATH,
            data=json.dumps(FRAME),
            headers={"Origin": "https://evil.example"},
        )
        assert blocked.status == 403
        assert state.frame.state is DisplayState.NO_TRACK

        with pytest.raises(WSServerHandshakeError) as refused:
            await client.ws_connect(WS_PATH, headers={"Origin": "https://evil.example"})
        assert refused.value.status == 403

        allowed = await client.post(WS_PATH, data=json.dumps(FRAME), headers={})
        assert allowed.status == 204


async def test_a_frame_that_is_not_text_is_rejected_not_a_server_error():
    receiver = AdapterReceiver(DisplayCoordinator(LyricsState()), ownership=SourceOwnershipCoordinator())
    async with TestClient(TestServer(receiver.build_app())) as client:
        response = await client.post(WS_PATH, data=b"\xff\xfe")
        assert response.status == 400


async def test_non_finite_snapshot_position_is_rejected():
    receiver = AdapterReceiver(DisplayCoordinator(LyricsState()), ownership=SourceOwnershipCoordinator())
    async with TestClient(TestServer(receiver.build_app())) as client:
        response = await client.post(
            WS_PATH,
            data=(
                '{"protocol":"kotonoha.adapter","version":1,"type":"snapshot",'
                '"adapter":"cider","sequence":0,"capturedAt":"now",'
                '"playback":{"playerId":"cider","status":"Playing",'
                '"positionS":1e1000,"track":null},"lyrics":null}'
            ),
        )

        assert response.status == 400


async def test_a_clock_carrying_nan_is_rejected():
    state = LyricsState()
    receiver = AdapterReceiver(DisplayCoordinator(state), ownership=SourceOwnershipCoordinator())
    async with TestClient(TestServer(receiver.build_app())) as client:
        response = await client.post(
            WS_PATH,
            data=(
                '{"protocol":"kotonoha.adapter","version":1,"type":"clock",'
                '"adapter":"cider","sequence":0,"capturedAt":"now",'
                '"positionS":NaN,"status":"Playing"}'
            ),
        )

        assert response.status == 400
        assert state.frame.state is DisplayState.NO_TRACK


async def test_disconnect_drops_gate_client():
    state = LyricsState()
    gate = SourceOwnershipCoordinator()
    receiver = AdapterReceiver(DisplayCoordinator(state), ownership=gate)
    async with TestClient(TestServer(receiver.build_app())) as client:
        ws = await client.ws_connect(WS_PATH)
        await ws.send_str(json.dumps(FRAME))
        await ws.close()

    assert gate.current_match(TrackMetadata("Song", "X")) is None
    assert state.frame.state is DisplayState.NO_TRACK
