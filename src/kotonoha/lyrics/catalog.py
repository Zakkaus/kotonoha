"""Compose the concrete lyric-source graph used by the application."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from .sources import ExactLyricsSource, LocalLyricsSource, LyricsSource


class LyricsSourceCatalog:
    """Own the concrete source adapters and exact-lookup routing graph.

    The resolver consumes this catalog as a dependency.  It does not construct
    network clients, local readers, or the live ownership adapter itself.
    """

    def __init__(
        self,
        providers: Mapping[str, LyricsSource],
        *,
        live_source: LyricsSource,
        local_source: LocalLyricsSource,
    ) -> None:
        self._sources = dict(providers)
        self._sources[live_source.source_id] = live_source
        self._local_source = local_source
        self._exact_source = ExactLyricsSource(self._sources, self._local_source)
        self._live_source_id = live_source.source_id

    @property
    def sources(self) -> Mapping[str, LyricsSource]:
        """Return an immutable view of the source slots used by the resolver."""
        return MappingProxyType(self._sources)

    @property
    def exact_source(self) -> ExactLyricsSource:
        """Return the exact-hint router for provider and local lookup."""
        return self._exact_source

    @property
    def live_source_id(self) -> str:
        """Return the configured source slot for live adapter candidates."""
        return self._live_source_id

    def close(self) -> None:
        """Release workers owned by local/exact source adapters."""
        self._local_source.close()

    def start(self) -> None:
        """Reopen workers owned by local/exact source adapters."""
        self._local_source.start()


__all__ = ["LyricsSourceCatalog"]
