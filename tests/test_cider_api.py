import asyncio
from typing import cast

import aiohttp
import pytest

from kotonoha.display.coordinator import DisplayCoordinator
from kotonoha.display.models import DisplayState
from kotonoha.lyrics.cider_api import CiderLyricsResponseAdapter
from kotonoha.lyrics.models import LyricsDocument, TimingKind
from kotonoha.lyrics.ownership import SourceOwnershipCoordinator
from kotonoha.playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity
from kotonoha.providers.cider_api import CiderApiProvider
from kotonoha.providers.cider_client import CiderApiClient, CiderPlaybackResponseAdapter
from kotonoha.state import LyricsState


def _playback_payload() -> dict[str, object]:
    return {
        "state": "playing",
        "nowPlaying": {
            "name": "Song",
            "artistName": "Artist",
            "albumName": "Album",
            "durationInMillis": 180000,
            "playParams": {"id": "song-1", "catalogId": "song-1"},
            "url": "https://music.apple.com/song-1",
            "currentPlaybackTime": 12.0,
        },
        "time": {"currentTime": 12.5, "duration": 180.0, "remaining": 167.5},
    }


def _lyrics_payload(provider: str = "Apple Music") -> dict[str, object]:
    return {
        "id": "song-1",
        "source": {"provider": provider, "timingType": "Line", "language": "en"},
        "lines": [
            {"start": 1.0, "end": 3.0, "text": "hello", "empty": False},
            {"start": 4.0, "end": 6.0, "text": "world", "empty": False},
        ],
    }


def test_cider_playback_adapter_uses_catalog_play_params_id():
    observation = CiderPlaybackResponseAdapter().adapt(_playback_payload(), observed_at=10.0)

    assert observation.status is PlaybackStatus.PLAYING
    assert observation.position_s == 12.5
    assert observation.duration_s == 180.0
    assert observation.track is not None
    assert observation.track.stable_id == "song-1"
    assert observation.track.track_ref == "cider:cider-api:song-1"


def test_cider_playback_adapter_drops_stale_now_playing_after_stop():
    payload = _playback_payload()
    payload["state"] = "stopped"

    observation = CiderPlaybackResponseAdapter().adapt(payload, observed_at=10.0)

    assert observation.status is PlaybackStatus.STOPPED
    assert observation.track is None
    assert observation.position_s is None
    assert observation.duration_s is None


def test_cider_lyrics_adapter_keeps_the_final_provider_identity():
    track = TrackIdentity("cider", "cider-api", "song-1", "Song", "Song", "Artist", "Album", None, 180.0)
    document = CiderLyricsResponseAdapter().adapt(_lyrics_payload(), track=track, duration_s=180.0)

    assert document.source_id == "apple-music"
    assert document.source_name == "Apple Music"
    assert document.song_id == "song-1"
    assert document.timing is TimingKind.LINE
    assert document.lines[0].end == 3.0


def test_cider_lyrics_adapter_preserves_unknown_provider_name_separately():
    track = TrackIdentity("cider", "cider-api", "song-1", "Song", "Song", "Artist", "Album", None, 180.0)
    document = CiderLyricsResponseAdapter().adapt(
        _lyrics_payload("A New Provider"), track=track, duration_s=180.0
    )

    assert document.source_id == "a-new-provider"
    assert document.source_name == "A New Provider"


def test_cider_lyrics_adapter_keeps_non_ascii_provider_ids_distinct():
    track = TrackIdentity("cider", "cider-api", "song-1", "Song", "Song", "Artist", "Album", None, 180.0)
    document = CiderLyricsResponseAdapter().adapt(
        _lyrics_payload("QQ音乐"), track=track, duration_s=180.0
    )

    assert document.source_id.startswith("provider-")
    assert document.source_id != "unknown"
    assert document.source_name == "QQ音乐"


def test_cider_lyrics_adapter_rejects_lines_without_timing_type():
    track = TrackIdentity("cider", "cider-api", "song-1", "Song", "Song", "Artist", "Album", None, 180.0)
    payload = _lyrics_payload()
    payload["source"] = {"provider": "Apple Music", "timingType": "None", "language": "en"}

    with pytest.raises(ValueError, match="timing type"):
        CiderLyricsResponseAdapter().adapt(payload, track=track, duration_s=180.0)


def test_cider_lyrics_adapter_allows_empty_line_text():
    track = TrackIdentity("cider", "cider-api", "song-1", "Song", "Song", "Artist", "Album", None, 180.0)
    payload = _lyrics_payload()
    payload["lines"] = [{"start": 1.0, "end": 3.0, "text": "", "empty": True}]

    document = CiderLyricsResponseAdapter().adapt(payload, track=track, duration_s=180.0)

    assert document.lines[0].text == ""


class _FakeContent:
    async def read(self, _limit: int) -> bytes:
        return ("{\"data\":" + _json_payload() + "}").encode()


class _FakeResponse:
    status = 200

    def __init__(self) -> None:
        self.content = _FakeContent()

    async def __aenter__(self):
        return self

    async def __aexit__(self, _type, _value, _traceback):
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.headers: list[dict[str, str]] = []

    def get(self, _url, *, params, headers):
        del params
        self.headers.append(headers)
        return _FakeResponse()


def _json_payload() -> str:
    import json

    return json.dumps(_playback_payload())


@pytest.mark.asyncio
@pytest.mark.parametrize("token, expected_header", [(None, None), ("secret", "secret"), ("", None)])
async def test_cider_client_sends_an_apptoken_only_when_configured(token, expected_header):
    session = _FakeSession()
    client = CiderApiClient(token=token, session=cast(aiohttp.ClientSession, session))
    await client.start()
    await client.playback(observed_at=1.0)
    await client.close()

    assert session.headers[0].get("apptoken") == expected_header


@pytest.mark.asyncio
async def test_cider_client_runtime_token_can_be_changed():
    session = _FakeSession()
    client = CiderApiClient(token=None, session=cast(aiohttp.ClientSession, session))
    await client.start()
    client.set_token("  test-token  ")
    await client.playback(observed_at=1.0)
    client.set_token("")
    await client.playback(observed_at=2.0)
    await client.close()

    assert session.headers[0].get("apptoken") == "test-token"
    assert session.headers[1].get("apptoken") is None


class _FakeCiderClient:
    def __init__(self, observation: PlaybackObservation, document: LyricsDocument) -> None:
        self.observation = observation
        self.document = document
        self.playback_called = asyncio.Event()
        self.lyrics_called = asyncio.Event()
        self.token: str | None = None

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def set_token(self, token: str | None) -> None:
        self.token = token

    async def playback(self, *, observed_at: float) -> PlaybackObservation:
        self.playback_called.set()
        return PlaybackObservation(
            self.observation.adapter_id,
            self.observation.player_id,
            self.observation.track,
            self.observation.status,
            self.observation.position_s,
            self.observation.duration_s,
            observed_at,
        )

    async def lyrics(self, track: TrackIdentity, *, translation_language: str | None) -> LyricsDocument:
        del track, translation_language
        self.lyrics_called.set()
        return self.document


class _BlockingCiderClient(_FakeCiderClient):
    def __init__(self, observation: PlaybackObservation, document: LyricsDocument) -> None:
        super().__init__(observation, document)
        self.release_lyrics = asyncio.Event()
        self.cancel_started = asyncio.Event()
        self.release_cancellation = asyncio.Event()
        self.lyrics_finished = asyncio.Event()
        self.close_called = asyncio.Event()
        self.close_observed_lyrics_finished: bool | None = None
        self.hold_cancellation = False

    async def lyrics(self, track: TrackIdentity, *, translation_language: str | None) -> LyricsDocument:
        self.lyrics_called.set()
        try:
            await self.release_lyrics.wait()
            return await super().lyrics(track, translation_language=translation_language)
        except asyncio.CancelledError:
            self.cancel_started.set()
            if self.hold_cancellation:
                await self.release_cancellation.wait()
            raise
        finally:
            self.lyrics_finished.set()

    async def close(self) -> None:
        self.close_observed_lyrics_finished = self.lyrics_finished.is_set()
        self.close_called.set()
        await super().close()


@pytest.mark.asyncio
async def test_cider_provider_publishes_canonical_document_and_final_provider_name():
    track = TrackIdentity("cider", "cider-api", "song-1", "Song", "Song", "Artist", "Album", None, 180.0)
    observation = PlaybackObservation("cider", "cider-api", track, PlaybackStatus.PLAYING, 1.5, 180.0, 1.0)
    document = CiderLyricsResponseAdapter().adapt(_lyrics_payload(), track=track, duration_s=180.0)
    client = _FakeCiderClient(observation, document)
    state = LyricsState()
    provider = CiderApiProvider(
        display=DisplayCoordinator(state),
        ownership=SourceOwnershipCoordinator(),
        client=client,
        poll_interval=60.0,
    )

    await provider.start()
    await asyncio.wait_for(client.playback_called.wait(), timeout=1.0)
    await asyncio.wait_for(client.lyrics_called.wait(), timeout=1.0)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    try:
        assert state.frame.state is DisplayState.LYRICS_AVAILABLE
        assert state.frame.document is not None
        assert state.frame.document.source_id == "apple-music"
        assert state.frame.document.source_name == "Apple Music"
        assert state.frame.track is not None
        assert state.frame.track.stable_id == "song-1"
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_cider_provider_publishes_resolving_while_lyrics_are_pending():
    track = TrackIdentity("cider", "cider-api", "song-1", "Song", "Song", "Artist", "Album", None, 180.0)
    observation = PlaybackObservation("cider", "cider-api", track, PlaybackStatus.PLAYING, 1.5, 180.0, 1.0)
    document = CiderLyricsResponseAdapter().adapt(_lyrics_payload(), track=track, duration_s=180.0)
    client = _BlockingCiderClient(observation, document)
    state = LyricsState()
    provider = CiderApiProvider(
        display=DisplayCoordinator(state),
        ownership=SourceOwnershipCoordinator(),
        client=client,
        poll_interval=60.0,
    )

    await provider.start()
    try:
        await asyncio.wait_for(client.lyrics_called.wait(), timeout=1.0)
        assert state.frame.state is DisplayState.RESOLVING
        assert state.frame.document is None
    finally:
        await provider.stop()


@pytest.mark.asyncio
async def test_cider_provider_stop_waits_for_a_disabled_lyrics_task():
    track = TrackIdentity("cider", "cider-api", "song-1", "Song", "Song", "Artist", "Album", None, 180.0)
    observation = PlaybackObservation("cider", "cider-api", track, PlaybackStatus.PLAYING, 1.5, 180.0, 1.0)
    document = CiderLyricsResponseAdapter().adapt(_lyrics_payload(), track=track, duration_s=180.0)
    client = _BlockingCiderClient(observation, document)
    client.hold_cancellation = True
    state = LyricsState()
    provider = CiderApiProvider(
        display=DisplayCoordinator(state),
        ownership=SourceOwnershipCoordinator(),
        client=client,
        poll_interval=60.0,
    )

    await provider.start()
    await asyncio.wait_for(client.lyrics_called.wait(), timeout=1.0)
    provider.set_enabled(False)
    await asyncio.wait_for(client.cancel_started.wait(), timeout=1.0)

    stop_task = asyncio.create_task(provider.stop())
    try:
        await asyncio.wait_for(asyncio.shield(client.close_called.wait()), timeout=0.05)
        closed_before_cancellation_finished = True
    except TimeoutError:
        closed_before_cancellation_finished = False
    client.release_cancellation.set()
    await stop_task

    assert closed_before_cancellation_finished is False
    assert client.close_observed_lyrics_finished is True
