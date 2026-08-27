import asyncio
import contextlib

import pytest

from kotonoha.lyrics.hint import LyricsHint
from kotonoha.lyrics.match import TrackMetadata
from kotonoha.lyrics.models import LyricLine, LyricsDocument, TimingKind
from kotonoha.lyrics.sources import LyricsSourceResult
from kotonoha.lyrics.workflow import (
    DocumentResolution,
    LyricsResolutionWorkflow,
    ResolverLookup,
    SourcePlan,
)

TRACK = TrackMetadata("Song", "Artist", "Album", 180.0)
LINES = (LyricLine(0, "L0", 0.0, 5.0, "hello", ""),)


class RecordingResolver:
    def __init__(self) -> None:
        self.hints: list[LyricsHint] = []
        self.sources: list[list[str]] = []

    async def resolve(self, _session, _track, sources, /):
        self.sources.append(sources)
        return LyricsSourceResult(
            "sidecar",
            document=LyricsDocument("sidecar", timing=TimingKind.LINE, lines=LINES),
        )

    async def resolve_hint(self, _session, _track, sources, hint, /):
        self.hints.append(hint)
        self.sources.append(sources)
        return None

    async def resolve_with_diagnostics(self, session, track, sources, /):
        return ResolverLookup(await self.resolve(session, track, sources))


async def test_workflow_falls_back_after_an_exact_hint_miss_and_returns_document():
    resolver = RecordingResolver()
    workflow = LyricsResolutionWorkflow(resolver)

    decision = await workflow.resolve(
        None,
        TRACK,
        SourcePlan.from_sources(["sidecar", "netease"]),
        generation=4,
        hint=LyricsHint("netease", "123"),
    )

    assert isinstance(decision, DocumentResolution)
    assert decision.generation == 4
    assert decision.source_id == "sidecar"
    assert decision.document.lines == LINES
    assert resolver.hints == [LyricsHint("netease", "123")]
    assert resolver.sources == [["sidecar", "netease"], ["sidecar", "netease"]]


async def test_workflow_cancellation_releases_owned_resolution_task():
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class BlockingResolver:
        async def resolve_with_diagnostics(self, _session, _track, _sources, /):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return ResolverLookup(None)

        async def resolve(self, session, track, sources, /):
            return (await self.resolve_with_diagnostics(session, track, sources)).result

        async def resolve_hint(self, _session, _track, _sources, _hint, /):
            return None

    workflow = LyricsResolutionWorkflow(BlockingResolver())
    task = asyncio.create_task(
        workflow.resolve(None, TRACK, SourcePlan.from_sources(["netease"]), generation=5)
    )
    await started.wait()

    await workflow.cancel_all()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()


async def test_new_generation_waits_for_old_generation_cancellation():
    started = asyncio.Event()
    cancelled = asyncio.Event()
    release_cancellation = asyncio.Event()
    second_started = asyncio.Event()

    class BlockingResolver:
        def __init__(self) -> None:
            self._calls = 0

        async def resolve_with_diagnostics(self, _session, _track, _sources, /):
            self._calls += 1
            if self._calls == 1:
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    await release_cancellation.wait()
                    raise
            second_started.set()
            await asyncio.Event().wait()
            return ResolverLookup(None)

        async def resolve(self, session, track, sources, /):
            return (await self.resolve_with_diagnostics(session, track, sources)).result

        async def resolve_hint(self, _session, _track, _sources, _hint, /):
            return None

    workflow = LyricsResolutionWorkflow(BlockingResolver())
    first = asyncio.create_task(
        workflow.resolve(None, TRACK, SourcePlan.from_sources(["netease"]), generation=1)
    )
    await started.wait()

    second = asyncio.create_task(
        workflow.resolve(None, TRACK, SourcePlan.from_sources(["netease"]), generation=2)
    )
    await cancelled.wait()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(second_started.wait(), timeout=0.01)

    release_cancellation.set()
    await second_started.wait()
    await workflow.cancel_all()
    with contextlib.suppress(asyncio.CancelledError):
        await first
    with contextlib.suppress(asyncio.CancelledError):
        await second
