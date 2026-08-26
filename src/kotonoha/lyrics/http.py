"""Small HTTP capability shared by lyric provider implementations."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import Protocol

import aiohttp


class LyricsResponseContent(Protocol):
    """Bounded response body reader needed by lyric payload parsers."""

    async def read(self, size: int = -1, /) -> bytes: ...


class LyricsResponse(Protocol):
    """The response facts consumed by provider boundary helpers."""

    status: int

    @property
    def content(self) -> LyricsResponseContent: ...

    def raise_for_status(self) -> None: ...

    async def __aenter__(self) -> LyricsResponse: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
        /,
    ) -> None: ...


class LyricsSession(Protocol):
    """HTTP capability exposed to lyric sources instead of a concrete client."""

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: object | None = None,
    ) -> AbstractAsyncContextManager[LyricsResponse]: ...

    def post(
        self,
        url: str,
        *,
        json: object | None = None,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: object | None = None,
    ) -> AbstractAsyncContextManager[LyricsResponse]: ...

    async def close(self) -> None: ...


class AioHttpLyricsSession:
    """Adapt one aiohttp session to the toolkit-neutral lyric HTTP port."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: object | None = None,
    ) -> AbstractAsyncContextManager[LyricsResponse]:
        """Forward a validated request to aiohttp."""
        return self._session.get(
            url,
            params=params,
            headers=headers,
            timeout=_aiohttp_timeout(timeout),
        )

    def post(
        self,
        url: str,
        *,
        json: object | None = None,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: object | None = None,
    ) -> AbstractAsyncContextManager[LyricsResponse]:
        """Forward a validated request to aiohttp."""
        return self._session.post(
            url,
            json=json,
            params=params,
            headers=headers,
            timeout=_aiohttp_timeout(timeout),
        )

    async def close(self) -> None:
        """Close the wrapped client session."""
        await self._session.close()


def _aiohttp_timeout(value: object | None) -> aiohttp.ClientTimeout | None:
    """Accept only timeout values supported by the concrete HTTP adapter."""
    if value is None or isinstance(value, aiohttp.ClientTimeout):
        return value
    if isinstance(value, (int, float)):
        return aiohttp.ClientTimeout(total=float(value))
    raise TypeError("unsupported lyric HTTP timeout")


__all__ = ["AioHttpLyricsSession", "LyricsResponse", "LyricsResponseContent", "LyricsSession"]
