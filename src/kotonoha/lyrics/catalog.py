"""Compose the concrete lyric-source graph used by the application."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from . import kugou, lrclib, netease, qqmusic
from .artifact import LyricsArtifact
from .http import LyricsSession
from .live_source import LiveLyricsSource, LiveSourcePort
from .match import MatchConfidence, TrackMetadata
from .network_sources import NetworkLyricsSource
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
        local_source: LocalLyricsSource | None = None,
    ) -> None:
        self._sources = dict(providers)
        self._sources[live_source.source_id] = live_source
        self._local_source = local_source if local_source is not None else LocalLyricsSource()
        self._exact_source = ExactLyricsSource(self._sources, self._local_source)
        self._live_source_id = live_source.source_id

    @classmethod
    def default(cls, ownership: LiveSourcePort) -> LyricsSourceCatalog:
        """Build the production network, live, local, and exact source graph."""
        return cls(
            _default_network_sources(),
            live_source=LiveLyricsSource(ownership),
        )

    @classmethod
    def from_providers(
        cls,
        providers: Mapping[str, LyricsSource],
        ownership: LiveSourcePort,
        *,
        live_source: LyricsSource | None = None,
        local_source: LocalLyricsSource | None = None,
    ) -> LyricsSourceCatalog:
        """Build a test or embedded catalog around explicitly supplied providers."""
        selected_live = live_source if live_source is not None else LiveLyricsSource(ownership)
        return cls(providers, live_source=selected_live, local_source=local_source)

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


def _default_network_sources() -> dict[str, LyricsSource]:
    """Create network adapters without starting any I/O."""
    return {
        "netease": NetworkLyricsSource(
            "netease", netease.fetch_artifact, netease.parse_payload, exact_fetch=_netease_exact
        ),
        "qqmusic": NetworkLyricsSource(
            "qqmusic", qqmusic.fetch_artifact, qqmusic.parse_payload, exact_fetch=_qqmusic_exact
        ),
        "lrclib": NetworkLyricsSource("lrclib", lrclib.fetch_artifact, lrclib.parse_payload),
        "kugou": NetworkLyricsSource("kugou", kugou.fetch_artifact, kugou.parse_payload),
    }


async def _netease_exact(
    session: LyricsSession,
    track: TrackMetadata,
    song_id: str,
) -> LyricsArtifact | None:
    """Fetch the exact Netease payload selected by a player hint."""
    payload = await netease.fetch_payload(session, song_id)
    lines = netease.parse_payload(payload)
    if not lines:
        return None
    return LyricsArtifact(
        provider="netease",
        provider_song_id=song_id,
        title=track.title,
        artist=track.artist,
        album=track.album,
        duration_s=track.duration_s,
        payload=payload,
        lines=lines,
        confidence=MatchConfidence.HIGH,
    )


async def _qqmusic_exact(
    session: LyricsSession,
    track: TrackMetadata,
    song_id: str,
) -> LyricsArtifact | None:
    """Fetch the exact QQ Music payload selected by a player hint."""
    payload = await qqmusic.fetch_payload_for_song_id(session, song_id)
    lines = qqmusic.parse_payload(payload)
    if not lines:
        return None
    return LyricsArtifact(
        provider="qqmusic",
        provider_song_id=song_id,
        title=track.title,
        artist=track.artist,
        album=track.album,
        duration_s=track.duration_s,
        payload=payload,
        lines=lines,
        confidence=MatchConfidence.HIGH,
    )


__all__ = ["LyricsSourceCatalog"]
