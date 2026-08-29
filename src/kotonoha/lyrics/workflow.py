"""Generation-owned lyric resolution decisions for player workflows."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, TypeAlias

from ..async_task import create_owned_task, wait_for_owned
from .hint import LyricsHint
from .http import LyricsSession
from .match import MatchConfidence, TrackMetadata
from .models import LyricsDocument
from .sources import LyricsSourceKind, LyricsSourceResult


@dataclass(frozen=True)
class SourcePlan:
    """The ordered source names a workflow execution is allowed to query."""

    sources: tuple[str, ...]

    @classmethod
    def from_sources(cls, sources: Sequence[str]) -> SourcePlan:
        """Capture a stable source order for one resolution generation."""
        return cls(tuple(source for source in sources if source))


@dataclass(frozen=True)
class DocumentResolution:
    """A resolved canonical lyric document from a provider or local source."""

    generation: int
    source_id: str
    document: LyricsDocument
    confidence: MatchConfidence
    duration_s: float | None
    source_kind: LyricsSourceKind = LyricsSourceKind.NETWORK


@dataclass(frozen=True)
class NoLyricsResolution:
    """A completed lookup with no usable lyric source result."""

    generation: int
    reason: str
    unreachable_sources: frozenset[str] = frozenset()


ResolutionDecision: TypeAlias = DocumentResolution | NoLyricsResolution


@dataclass(frozen=True)
class ResolverLookup:
    """One resolver result plus failures belonging only to that request."""

    result: LyricsSourceResult | None
    unreachable_sources: frozenset[str] = frozenset()


class WorkflowResolverPort(Protocol):
    """The narrow lookup capability needed by one workflow generation."""

    async def resolve(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        sources: list[str],
        /,
    ) -> LyricsSourceResult | None: ...

    async def resolve_with_diagnostics(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        sources: list[str],
        /,
    ) -> ResolverLookup: ...

    async def resolve_hint(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        sources: list[str],
        hint: LyricsHint,
        /,
    ) -> LyricsSourceResult | None: ...

class ResolverPort(WorkflowResolverPort, Protocol):
    """The full resolver capability used by provider configuration."""

    @property
    def live_source_id(self) -> str: ...

    def start(self) -> None: ...

    def reset_memory(self) -> None: ...

    def set_cache_enabled(self, enabled: bool, /) -> None: ...

    def set_prefer_best(self, enabled: bool, /) -> None: ...

    def set_fuzzy(self, enabled: bool, /) -> None: ...

    async def cancel_inflight(self) -> None: ...

    async def close(self) -> None: ...


class LyricsResolutionWorkflow:
    """Own one generation's resolver task and canonicalize its outcome."""

    def __init__(
        self,
        resolver: WorkflowResolverPort,
    ) -> None:
        self._resolver = resolver
        self._tasks: dict[int, asyncio.Task[ResolutionDecision]] = {}

    async def resolve(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        plan: SourcePlan,
        *,
        generation: int,
        hint: LyricsHint | None = None,
    ) -> ResolutionDecision:
        """Resolve one generation, falling back from an exact hint when needed."""
        cancelled: list[asyncio.Task[ResolutionDecision]] = []
        for active_generation, active_task in tuple(self._tasks.items()):
            if active_generation < generation and not active_task.done():
                active_task.cancel()
                cancelled.append(active_task)
        previous = self._tasks.get(generation)
        if previous is not None and not previous.done():
            previous.cancel()
            cancelled.append(previous)
        if cancelled:
            joined = asyncio.gather(*cancelled, return_exceptions=True)
            if await wait_for_owned(joined):
                raise asyncio.CancelledError
        task = create_owned_task(
            self._resolve_once(session, track, plan, generation, hint),
            name=f"kotonoha-lyrics-resolution-{generation}",
        )
        self._tasks[generation] = task
        try:
            return await task
        finally:
            if self._tasks.get(generation) is task:
                self._tasks.pop(generation, None)

    async def cancel_all(self) -> None:
        """Cancel and await all resolution tasks owned by this workflow."""
        tasks = tuple(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            joined = asyncio.gather(*tasks, return_exceptions=True)
            if await wait_for_owned(joined):
                raise asyncio.CancelledError

    async def _resolve_once(
        self,
        session: LyricsSession | None,
        track: TrackMetadata,
        plan: SourcePlan,
        generation: int,
        hint: LyricsHint | None,
    ) -> ResolutionDecision:
        """Run hint/network fallback and reject provider output that violates timing invariants."""
        result: LyricsSourceResult | None = None
        if hint is not None:
            result = await self._resolver.resolve_hint(session, track, list(plan.sources), hint)
        if result is None:
            lookup = await self._resolver.resolve_with_diagnostics(session, track, list(plan.sources))
            result = lookup.result
        else:
            lookup = ResolverLookup(result)
        if result is None:
            return NoLyricsResolution(generation, "no-source-result", lookup.unreachable_sources)
        document = result.document
        return DocumentResolution(
            generation,
            result.source_id,
            document,
            result.confidence,
            result.duration_s,
            result.source_kind,
        )


__all__ = [
    "DocumentResolution",
    "LyricsResolutionWorkflow",
    "NoLyricsResolution",
    "ResolutionDecision",
    "ResolverPort",
    "ResolverLookup",
    "SourcePlan",
    "WorkflowResolverPort",
]
