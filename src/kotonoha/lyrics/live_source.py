"""Live adapter source backed by normalized external playback facts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from .hint import LyricsHint
from .http import LyricsSession
from .match import TrackMetadata
from .sources import LyricsSourceKind, LyricsSourceResult, PayloadParser

if TYPE_CHECKING:
    from .live_contracts import LiveSourceMatch


class LiveSourcePort(Protocol):
    """Ownership operations required by the live source adapter."""

    def current_match(self, track: TrackMetadata, /) -> LiveSourceMatch | None: ...


class LiveLyricsSource:
    """Expose the current external adapter candidate as a normal lyric source."""

    def __init__(self, ownership: LiveSourcePort, source_id: str = "cider") -> None:
        if not source_id:
            raise ValueError("live lyric source id must not be empty")
        self._ownership = ownership
        self._source_id = source_id

    @property
    def source_id(self) -> str:
        """Return the configured source slot used by the resolver."""
        return self._source_id

    @property
    def cache_parser(self) -> PayloadParser | None:
        """Live documents are supplied by an adapter and are never cached here."""
        return None

    async def resolve(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        *,
        fuzzy: bool,
    ) -> LyricsSourceResult | None:
        """Return the matching live document without performing network I/O."""
        del session, fuzzy
        match = self._ownership.current_match(track)
        if match is None:
            return None
        return LyricsSourceResult(
            source_id=self._source_id,
            document=match.document,
            confidence=match.confidence,
            duration_s=match.document.duration_s,
            source_kind=LyricsSourceKind.LIVE,
        )

    async def resolve_exact(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        hint: LyricsHint,
    ) -> LyricsSourceResult | None:
        """Live adapters do not expose provider-id exact lookup."""
        del session, track, hint
        return None


__all__ = ["LiveLyricsSource", "LiveSourcePort"]
