"""Typed HTTP boundary for the local Cider API."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Final
from urllib.parse import quote

import aiohttp

from ..lyrics.cider_api import CiderLyricsPayloadError, CiderLyricsResponseAdapter
from ..lyrics.models import LyricsDocument
from ..playback.models import PlaybackObservation, PlaybackStatus, TrackIdentity

DEFAULT_CIDER_API_URL: Final[str] = "http://127.0.0.1:10767"
MAX_CIDER_RESPONSE_BYTES: Final[int] = 4 * 1024 * 1024


class CiderApiError(RuntimeError):
    """A Cider HTTP request or response failed at the integration boundary."""

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class CiderLyricsNotFound(CiderApiError):
    """Cider answered that no lyrics are available for the requested track."""


@dataclass(frozen=True)
class CiderPlaybackResponseAdapter:
    """Convert the `/playback` data object into the shared playback contract."""

    adapter_id: str = "cider"
    player_id: str = "cider-api"

    def adapt(self, payload: Mapping[str, object], *, observed_at: float) -> PlaybackObservation:
        """Parse one Cider playback data object and reject malformed facts."""
        status = PlaybackStatus.from_wire(payload.get("state"))
        if status is None:
            raise CiderApiError("Cider playback has an unknown state")
        time_data = _mapping(payload.get("time"), "playback.time")
        item_value = payload.get("nowPlaying")
        track = None if status is PlaybackStatus.STOPPED or item_value is None else self._track(item_value)
        position_s = (
            None
            if status is PlaybackStatus.STOPPED
            else _optional_number(time_data.get("currentTime"), "playback.time.currentTime", minimum=0.0)
        )
        if position_s is None and track is not None:
            position_s = _optional_number(
                track_value(item_value, "currentPlaybackTime"),
                "nowPlaying.currentPlaybackTime",
                minimum=0.0,
            )
        duration_s = (
            None
            if status is PlaybackStatus.STOPPED
            else _optional_number(time_data.get("duration"), "playback.time.duration", minimum=0.0)
        )
        if duration_s is None and track is not None:
            duration_s = track.duration_s
        if track is not None and track.duration_s != duration_s:
            track = TrackIdentity(
                adapter_id=track.adapter_id,
                player_id=track.player_id,
                stable_id=track.stable_id,
                title=track.title,
                raw_title=track.raw_title,
                artist=track.artist,
                album=track.album,
                url=track.url,
                duration_s=duration_s,
            )
        return PlaybackObservation(
            adapter_id=self.adapter_id,
            player_id=self.player_id,
            track=track,
            status=status,
            position_s=position_s,
            duration_s=duration_s,
            observed_at=observed_at,
        )

    def _track(self, value: object) -> TrackIdentity:
        item = _mapping(value, "playback.nowPlaying")
        play_params = _mapping(item.get("playParams"), "nowPlaying.playParams")
        stable_id = _text(play_params.get("id"), "nowPlaying.playParams.id")
        title = _text(item.get("name"), "nowPlaying.name")
        artist = _text(item.get("artistName"), "nowPlaying.artistName")
        album = _text(item.get("albumName"), "nowPlaying.albumName")
        url = _optional_text(item.get("url"), "nowPlaying.url")
        duration_ms = _optional_number(item.get("durationInMillis"), "nowPlaying.durationInMillis", minimum=0.0)
        duration_s = None if duration_ms is None else duration_ms / 1000.0
        return TrackIdentity(
            adapter_id=self.adapter_id,
            player_id=self.player_id,
            stable_id=stable_id,
            title=title,
            raw_title=title,
            artist=artist,
            album=album,
            url=url,
            duration_s=duration_s,
        )


class CiderApiClient:
    """Own one authenticated-or-anonymous Cider HTTP session.

    The token is intentionally optional because Cider can run with API
    authentication disabled. A non-empty token is sent as `apptoken`; an empty
    credential never becomes an empty authentication header.
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_CIDER_API_URL,
        token: str | None = None,
        session: aiohttp.ClientSession | None = None,
        playback_adapter: CiderPlaybackResponseAdapter | None = None,
        lyrics_adapter: CiderLyricsResponseAdapter | None = None,
    ) -> None:
        normalized_url = base_url.rstrip("/")
        if not normalized_url.startswith(("http://", "https://")):
            raise ValueError("Cider API URL must use HTTP or HTTPS")
        self._base_url = normalized_url
        self._token = token.strip() if token is not None and token.strip() else None
        self._session = session
        self._owns_session = False
        self._playback_adapter = playback_adapter if playback_adapter is not None else CiderPlaybackResponseAdapter()
        self._lyrics_adapter = lyrics_adapter if lyrics_adapter is not None else CiderLyricsResponseAdapter()

    def set_token(self, token: str | None) -> None:
        """Replace the optional credential used by subsequent requests."""
        self._token = token.strip() if token is not None and token.strip() else None

    async def start(self) -> None:
        """Create the owned HTTP session, if one was not injected."""
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=12.0, connect=3.0),
                cookie_jar=aiohttp.DummyCookieJar(),
            )
            self._owns_session = True

    async def close(self) -> None:
        """Close only the session owned by this client."""
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None
            self._owns_session = False

    async def playback(self, *, observed_at: float) -> PlaybackObservation:
        """Fetch and normalize the complete Cider playback snapshot."""
        data = await self._get_data("/api/v2/playback")
        return self._playback_adapter.adapt(data, observed_at=observed_at)

    async def lyrics(
        self,
        track: TrackIdentity,
        *,
        translation_language: str | None = None,
    ) -> LyricsDocument:
        """Fetch one track's structured lyrics and optional line translations."""
        if track.stable_id is None:
            raise CiderLyricsNotFound("Cider track has no catalog id", code="NO_TRACK_ID")
        try:
            data = await self._get_data("/api/v2/lyrics/current", params={"words": "true"})
        except CiderApiError as exc:
            if exc.code not in {"LYRICS_NOT_FOUND", "NO_CURRENT_TRACK"}:
                raise
            data = await self._get_data(f"/api/v2/lyrics/{quote(track.stable_id, safe='')}", params={"words": "true"})
        try:
            document = self._lyrics_adapter.adapt(data, track=track, duration_s=track.duration_s)
        except CiderLyricsPayloadError as exc:
            raise CiderApiError(str(exc), code="INVALID_LYRICS_RESPONSE") from exc
        if document.song_id is not None and document.song_id != track.stable_id:
            data = await self._get_data(f"/api/v2/lyrics/{quote(track.stable_id, safe='')}", params={"words": "true"})
            try:
                document = self._lyrics_adapter.adapt(data, track=track, duration_s=track.duration_s)
            except CiderLyricsPayloadError as exc:
                raise CiderApiError(str(exc), code="INVALID_LYRICS_RESPONSE") from exc

        if translation_language and document.song_id is not None and document.lines:
            try:
                translation_data = await self._get_data(
                    f"/api/v2/lyrics/{quote(document.song_id, safe='')}/translations",
                    params={"language": translation_language},
                )
                translations = self._lyrics_adapter.translations(translation_data)
            except CiderApiError as exc:
                if exc.code != "LYRICS_TRANSLATIONS_NOT_FOUND":
                    raise
            else:
                document = _with_translations(document, translations)
        return document

    async def _get_data(self, path: str, *, params: Mapping[str, str] | None = None) -> Mapping[str, object]:
        """Read one bounded JSON response and unwrap its typed `data` object."""
        session = self._session
        if session is None:
            raise RuntimeError("CiderApiClient.start() must be called before requests")
        headers = {"Accept": "application/json"}
        if self._token is not None:
            headers["apptoken"] = self._token
        try:
            async with session.get(f"{self._base_url}{path}", params=params, headers=headers) as response:
                raw = await response.content.read(MAX_CIDER_RESPONSE_BYTES + 1)
                status = response.status
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise CiderApiError("Cider API request failed") from exc
        if len(raw) > MAX_CIDER_RESPONSE_BYTES:
            raise CiderApiError("Cider API response exceeds the byte limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CiderApiError("Cider API returned invalid JSON", status=status) from exc
        root = _mapping(payload, "Cider API response")
        error = root.get("error")
        if status >= 400 or error is not None:
            error_data = _mapping(error, "Cider API error")
            code = _optional_text(error_data.get("code"), "Cider API error code")
            message = _optional_text(error_data.get("message"), "Cider API error message") or "request failed"
            if code in {"LYRICS_NOT_FOUND", "NO_CURRENT_TRACK"}:
                raise CiderLyricsNotFound(message, status=status, code=code)
            raise CiderApiError(message, status=status, code=code)
        return _mapping(root.get("data"), "Cider API data")


def _with_translations(document: LyricsDocument, translations: tuple[str, ...]) -> LyricsDocument:
    """Attach line-ordered translations without changing source timing."""
    lines = tuple(
        replace(line, translation=translations[index])
        if index < len(translations)
        else line
        for index, line in enumerate(document.lines)
    )
    return replace(document, lines=lines)


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise CiderApiError(f"{field} must be an object")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CiderApiError(f"{field} must be a non-empty string")
    return value


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CiderApiError(f"{field} must be a string")
    return value


def _optional_number(value: object, field: str, *, minimum: float) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CiderApiError(f"{field} must be a number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < minimum:
        raise CiderApiError(f"{field} is outside its valid range")
    return parsed


def track_value(value: object, field: str) -> object:
    """Read one optional field from a now-playing object without leaking its map."""
    item = _mapping(value, "playback.nowPlaying")
    return item.get(field)


__all__ = [
    "CiderApiClient",
    "CiderApiError",
    "CiderLyricsNotFound",
    "CiderPlaybackResponseAdapter",
    "DEFAULT_CIDER_API_URL",
    "MAX_CIDER_RESPONSE_BYTES",
]
