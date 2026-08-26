"""Network-backed implementations of the source contract."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

import aiohttp

from .artifact import LyricsArtifact
from .hint import LyricsHint
from .http import LyricsSession
from .match import TrackMetadata
from .sources import LyricsSourceError, LyricsSourceResult, PayloadParser


class ProviderFetch(Protocol):
    """A network provider fetch accepting the resolver's fuzzy-match policy."""

    def __call__(
        self,
        session: LyricsSession,
        track: TrackMetadata,
        *,
        fuzzy: bool,
    ) -> Awaitable[LyricsArtifact | None]: ...


ExactFetch = Callable[[LyricsSession, TrackMetadata, str], Awaitable[LyricsArtifact | None]]


class NetworkLyricsSource:
    """Adapt one concrete network provider to the shared source contract."""

    def __init__(
        self,
        source_id: str,
        fetch: ProviderFetch,
        parse_payload: PayloadParser,
        *,
        exact_fetch: ExactFetch | None = None,
    ) -> None:
        if not source_id:
            raise ValueError("network lyric source id must not be empty")
        self._source_id = source_id
        self._fetch = fetch
        self._parse_payload = parse_payload
        self._exact_fetch = exact_fetch

    @property
    def source_id(self) -> str:
        """Return the stable configured source identifier."""
        return self._source_id

    @property
    def cache_parser(self) -> PayloadParser:
        """Return the parser used by the persistent cache boundary."""
        return self._parse_payload

    async def resolve(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        *,
        fuzzy: bool,
    ) -> LyricsSourceResult | None:
        """Fetch and normalize one metadata-matched network result."""
        if session is None:
            raise LyricsSourceError(f"network source {self._source_id!r} requires an HTTP session")
        try:
            artifact = await self._fetch(session, track, fuzzy=fuzzy)
        except aiohttp.ClientError as exc:
            raise LyricsSourceError(f"{self._source_id} HTTP request failed") from exc
        return None if artifact is None else LyricsSourceResult.from_artifact(artifact)

    async def resolve_exact(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        hint: LyricsHint,
    ) -> LyricsSourceResult | None:
        """Resolve an exact provider id when this source supports it."""
        if self._exact_fetch is None or hint.provider != self._source_id or hint.song_id is None:
            return None
        if session is None:
            raise LyricsSourceError(f"exact source {self._source_id!r} requires an HTTP session")
        try:
            artifact = await self._exact_fetch(session, track, hint.song_id)
        except aiohttp.ClientError as exc:
            raise LyricsSourceError(f"{self._source_id} exact HTTP request failed") from exc
        return None if artifact is None else LyricsSourceResult.from_artifact(artifact)


__all__ = ["ExactFetch", "NetworkLyricsSource", "ProviderFetch"]
