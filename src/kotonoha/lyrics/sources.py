"""Typed lyric-source contracts and concrete local/network adapters."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ..async_worker import BlockingWorkerPort
from .adapter import LyricsDocumentAdapter
from .artifact import LyricsArtifact
from .hint import LyricsHint
from .http import LyricsSession
from .local import load_embedded_lyrics, load_sidecar_lyrics
from .match import MatchConfidence, TrackMetadata
from .models import LyricLine, LyricsDocument

PayloadParser = Callable[[Mapping[str, str]], tuple[LyricLine, ...]]


class LyricsSourceKind(StrEnum):
    """Describe how a normalized lyric document entered the application."""

    NETWORK = "network"
    LIVE = "live"
    LOCAL = "local"


class LyricsSourceError(RuntimeError):
    """A source could not complete its lookup at its external boundary."""


@dataclass(frozen=True)
class LyricsSourceResult:
    """One normalized source result before display projection.

    ``cache_artifact`` is a persistence hand-off for cacheable network sources.
    It is excluded from equality because callers compare normalized source data,
    not a provider's raw payload. The document is deliberately the only lyric
    content crossing this boundary; display frames belong to the display layer.
    """

    source_id: str
    document: LyricsDocument
    confidence: MatchConfidence = MatchConfidence.NONE
    duration_s: float | None = None
    cache_artifact: LyricsArtifact | None = field(default=None, repr=False, compare=False)
    source_kind: LyricsSourceKind = LyricsSourceKind.NETWORK

    @classmethod
    def from_artifact(cls, artifact: LyricsArtifact) -> LyricsSourceResult:
        """Convert a provider artifact into the source contract."""
        return cls(
            source_id=artifact.provider,
            document=LyricsDocumentAdapter().adapt(
                artifact.lines,
                source_id=artifact.provider,
                song_id=artifact.provider_song_id,
                title=artifact.title,
                artist=artifact.artist,
                album=artifact.album,
                duration_s=artifact.duration_s,
            ),
            confidence=artifact.confidence,
            duration_s=artifact.duration_s,
            cache_artifact=artifact,
        )


class LyricsSource(Protocol):
    """Structural contract implemented by automatic and exact lyric sources."""

    @property
    def source_id(self) -> str: ...

    @property
    def cache_parser(self) -> PayloadParser | None: ...

    async def resolve(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        *,
        fuzzy: bool,
    ) -> LyricsSourceResult | None: ...

    async def resolve_exact(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        hint: LyricsHint,
    ) -> LyricsSourceResult | None: ...


class SidecarLyricsSource:
    """Read the timed lyric file adjacent to a local audio file."""

    @property
    def source_id(self) -> str:
        """Return the canonical sidecar source identifier."""
        return "sidecar"

    @property
    def cache_parser(self) -> PayloadParser | None:
        """Sidecar files are not persisted through the network cache."""
        return None

    def read(self, audio_path: Path) -> list[LyricLine]:
        """Read sidecar lines synchronously inside an owned worker."""
        return load_sidecar_lyrics(audio_path)


class EmbeddedLyricsSource:
    """Read timed lyric tags embedded in a local audio file."""

    @property
    def source_id(self) -> str:
        """Return the canonical embedded source identifier."""
        return "embedded"

    @property
    def cache_parser(self) -> PayloadParser | None:
        """Embedded tags are not persisted through the network cache."""
        return None

    def read(self, audio_path: Path) -> list[LyricLine]:
        """Read embedded lines synchronously inside an owned worker."""
        return load_embedded_lyrics(audio_path)


class LocalLyricsSource:
    """Compose sidecar and embedded sources for an exact local-file hint."""

    def __init__(
        self,
        sidecar: SidecarLyricsSource,
        embedded: EmbeddedLyricsSource,
        *,
        worker: BlockingWorkerPort,
    ) -> None:
        self._sidecar = sidecar
        self._embedded = embedded
        self._worker = worker

    def start(self) -> None:
        """Reopen the local reader worker after a previous provider shutdown."""
        self._worker.reopen()

    def close(self) -> None:
        """Release the local-file worker without blocking the event loop."""
        self._worker.close()

    @property
    def source_id(self) -> str:
        """Return the exact-hint source identifier."""
        return "local"

    @property
    def cache_parser(self) -> PayloadParser | None:
        """Local file reads do not have a provider payload cache."""
        return None

    async def resolve(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        *,
        fuzzy: bool,
    ) -> LyricsSourceResult | None:
        """Local files are opt-in through an exact player hint."""
        del session, track, fuzzy
        return None

    async def resolve_exact(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        hint: LyricsHint,
    ) -> LyricsSourceResult | None:
        """Read sidecar first, then embedded lyrics without blocking the event loop."""
        del session
        local_path = hint.local_path
        if hint.provider != self.source_id or local_path is None:
            return None

        def read() -> tuple[str, tuple[LyricLine, ...]]:
            sidecar = tuple(self._sidecar.read(local_path))
            if sidecar:
                return self._sidecar.source_id, sidecar
            return self._embedded.source_id, tuple(self._embedded.read(local_path))

        source_id, lines = await self._worker.run(read)
        if not lines:
            return None
        return LyricsSourceResult(
            source_id=source_id,
            document=LyricsDocumentAdapter().adapt(
                lines,
                source_id=source_id,
                title=track.title,
                artist=track.artist,
                album=track.album,
                duration_s=track.duration_s,
            ),
            confidence=MatchConfidence.HIGH,
            duration_s=track.duration_s,
            source_kind=LyricsSourceKind.LOCAL,
        )


class ExactLyricsSource:
    """Route a player-provided exact hint to the matching source adapter."""

    def __init__(self, sources: Mapping[str, LyricsSource], local: LocalLyricsSource) -> None:
        self._sources = dict(sources)
        self._local = local

    async def resolve(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        hint: LyricsHint,
        *,
        enabled_sources: tuple[str, ...],
    ) -> LyricsSourceResult | None:
        """Resolve only when the hinted source is enabled for this generation."""
        if hint.provider == self._local.source_id:
            return await self._local.resolve_exact(session, track, hint)
        if hint.provider not in enabled_sources:
            return None
        source = self._sources.get(hint.provider)
        if source is None:
            return None
        return await source.resolve_exact(session, track, hint)


__all__ = [
    "EmbeddedLyricsSource",
    "ExactLyricsSource",
    "LocalLyricsSource",
    "LyricsSource",
    "LyricsSourceError",
    "LyricsSourceKind",
    "LyricsSourceResult",
    "PayloadParser",
    "SidecarLyricsSource",
]
