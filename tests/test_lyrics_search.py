import asyncio
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any, cast

from PyQt6.QtWidgets import QPushButton

from kotonoha.app.lyrics_search import LyricsSearchController
from kotonoha.config import Config
from kotonoha.display.models import LyricsDisplayStatus
from kotonoha.lyrics.artifact import LyricsArtifact
from kotonoha.lyrics.cache import CacheWriteResult, CacheWriteStatus, LyricsCacheKey, LyricsCacheMode
from kotonoha.lyrics.http import LyricsResponse, LyricsSession
from kotonoha.lyrics.match import MatchConfidence, TrackMetadata
from kotonoha.lyrics.models import LyricLine, LyricsCacheState, LyricsOrigin
from kotonoha.lyrics.search import (
    LyricsSearchProvider,
    LyricsSearchQuery,
    LyricsSearchResponse,
    LyricsSearchResult,
    LyricsSearchService,
    LyricsSearchUnavailable,
)
from kotonoha.lyrics.search_policy import (
    MANUAL_SEARCH_RESULTS_PER_PROVIDER,
    MANUAL_SEARCH_RESULTS_TOTAL,
)
from kotonoha.platform import OverlayPlatformFactory
from kotonoha.platform.overlay_contracts import OverlayPlatformAdapters
from kotonoha.platform.qt_window import QtWindowPlatform
from kotonoha.ui.settings.lyrics_search_dialog import LyricsSearchDialog


class _Session:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: object | None = None,
    ) -> AbstractAsyncContextManager[LyricsResponse]:
        del url, params, headers, timeout
        raise AssertionError("search providers must not use the fake session directly")

    def post(
        self,
        url: str,
        *,
        json: object | None = None,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: object | None = None,
    ) -> AbstractAsyncContextManager[LyricsResponse]:
        del url, json, params, headers, timeout
        raise AssertionError("search providers must not use the fake session directly")

def _artifact(provider: str, song_id: str, text: str) -> LyricsArtifact:
    return LyricsArtifact(
        provider=provider,
        provider_song_id=song_id,
        title="Song",
        artist="Artist",
        album="Album",
        duration_s=180.0,
        payload={"lrc": f"[00:00.00]{text}"},
        lines=(LyricLine(0, song_id, 0.0, 5.0, text, ""),),
        confidence=MatchConfidence.HIGH,
    )

async def test_search_service_returns_multiple_results_and_isolates_failed_sources() -> None:
    session = _Session()

    async def first(_session: LyricsSession, _track) -> tuple[LyricsArtifact, ...]:
        return (_artifact("first", "1", "one"), _artifact("first", "2", "two"))

    async def failing(_session: LyricsSession, _track) -> tuple[LyricsArtifact, ...]:
        raise TimeoutError("provider timed out")

    service = LyricsSearchService({"first": first, "failing": failing}, lambda: session)
    await service.start()

    response = await service.search(LyricsSearchQuery("Song", "Artist"), ["first", "failing", "cider"])

    assert [result.source_key for result in response.results] == ["first:1", "first:2"]
    assert [(item.source, item.reason_key) for item in response.unavailable_sources] == [
        ("failing", "search.unavailable.timeout"),
        ("cider", "search.unavailable.unconfigured"),
    ]
    await service.stop()
    assert session.closed is True

async def test_search_service_applies_the_total_result_budget() -> None:
    session = _Session()

    def provider(source: str):
        async def search(_session: LyricsSession, _track) -> tuple[LyricsArtifact, ...]:
            return tuple(
                _artifact(source, str(index), f"{source}-{index}")
                for index in range(MANUAL_SEARCH_RESULTS_PER_PROVIDER)
            )

        return search

    sources = ("first", "second", "third", "fourth")
    service = LyricsSearchService({source: provider(source) for source in sources}, lambda: session)
    await service.start()

    response = await service.search(LyricsSearchQuery("Song", "Artist"), sources)

    assert len(response.results) == MANUAL_SEARCH_RESULTS_TOTAL
    await service.stop()

async def test_search_service_reports_a_declared_unavailable_provider() -> None:
    session = _Session()
    service = LyricsSearchService(
        {
            "qqmusic": LyricsSearchProvider(None, "search.unavailable.qqmusic")
        },
        lambda: session,
    )
    await service.start()

    response = await service.search(LyricsSearchQuery("Song", "Artist"), ["qqmusic"])

    assert response.results == ()
    assert response.unavailable_sources == (
        LyricsSearchUnavailable("qqmusic", "search.unavailable.qqmusic"),
    )
    await service.stop()

class _Signal:
    def __init__(self) -> None:
        self._slots: list[Callable[..., object]] = []

    def connect(self, slot: Callable[..., object]) -> None:
        self._slots.append(slot)

    def emit(self, *args: object) -> None:
        for slot in tuple(self._slots):
            slot(*args)

class _Dialog:

    def retheme(self, config: Config) -> None:
        """Accept a theme change the way the real window does."""
        self.themes.append(str(config.theme))

    def __init__(self) -> None:
        self.themes: list[str] = []
        self.intent_requested = _Signal()
        self.finished = _Signal()
        self.status = LyricsDisplayStatus()
        self.results: tuple[LyricsSearchResult, ...] = ()
        self.search_finished = asyncio.Event()
        self.apply_finished = asyncio.Event()
        self.apply_results: list[tuple[CacheWriteResult, bool]] = []

    def show(self) -> None:
        return None

    def close(self) -> None:
        self.finished.emit(0)

    def raise_(self) -> None:
        return None

    def activateWindow(self) -> None:
        return None

    def set_results(self, query: LyricsSearchQuery, response: LyricsSearchResponse) -> None:
        del query
        self.results = response.results

    def set_busy(self, busy: bool) -> None:
        if not busy and self.results:
            self.search_finished.set()

    def show_error(self, message: str) -> None:
        del message
        return None

    def show_apply_result(self, result: CacheWriteResult, displayed: bool) -> None:
        self.apply_results.append((result, displayed))
        self.apply_finished.set()

    def set_current_status(self, status: LyricsDisplayStatus) -> None:
        self.status = status

class _Factory:
    def __init__(self) -> None:
        self.dialog = _Dialog()
        self.status: LyricsDisplayStatus | None = None

    def create(self, config: Config, query: LyricsSearchQuery, status: LyricsDisplayStatus) -> _Dialog:
        del config, query
        self.status = status
        return self.dialog

class _ReopeningFactory:
    def __init__(self) -> None:
        self.dialogs: list[_Dialog] = []

    def create(self, config: Config, query: LyricsSearchQuery, status: LyricsDisplayStatus) -> _Dialog:
        del config, query, status
        dialog = _Dialog()
        self.dialogs.append(dialog)
        return dialog

class _QtFactory:
    def __init__(self, platform_factory: OverlayPlatformFactory | None = None) -> None:
        self._platform_factory = platform_factory
        self.dialogs: list[LyricsSearchDialog] = []

    def create(
        self,
        config: Config,
        query: LyricsSearchQuery,
        status: LyricsDisplayStatus,
    ) -> LyricsSearchDialog:
        dialog = LyricsSearchDialog(
            config,
            query,
            status=status,
            platform_factory=self._platform_factory,
        )
        self.dialogs.append(dialog)
        return dialog

def _ordinary_window_factory(host):
    platform = QtWindowPlatform(host)
    return OverlayPlatformAdapters(
        surface=platform,
        input_region=platform,
        blur=platform,
        placement=platform,
        output_binding=None,
        drag=platform,
    )

class _Cache:
    def __init__(self) -> None:
        self.writes: list[tuple[LyricsArtifact, LyricsCacheMode]] = []

    async def upsert(
        self,
        artifact: LyricsArtifact,
        *,
        mode: LyricsCacheMode = LyricsCacheMode.MANUAL,
    ) -> CacheWriteResult:
        self.writes.append((artifact, mode))
        status = CacheWriteStatus.CREATED if len(self.writes) == 1 else CacheWriteStatus.UPDATED
        return CacheWriteResult(LyricsCacheKey(artifact.provider, artifact.provider_song_id), status)

class _Searcher:
    def __init__(self, response: LyricsSearchResponse) -> None:
        self.response = response

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def search(self, query: LyricsSearchQuery, sources: Sequence[str]) -> LyricsSearchResponse:
        del query, sources
        return self.response

class _BlockingSearcher(_Searcher):
    def __init__(self, response: LyricsSearchResponse) -> None:
        super().__init__(response)
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.release = asyncio.Event()

    async def search(self, query: LyricsSearchQuery, sources: Sequence[str]) -> LyricsSearchResponse:
        del query, sources
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return self.response

async def test_search_controller_reapplies_candidates_and_refreshes_manual_status() -> None:
    first = LyricsSearchResult.from_artifact(_artifact("netease", "1", "first"))
    second = LyricsSearchResult.from_artifact(_artifact("lrclib", "2", "second"))
    factory = _Factory()
    cache = _Cache()
    active_status = LyricsDisplayStatus(
        playback_source="mpris",
        lyrics_source_id="lrclib",
        lyrics_source_name="LRCLIB",
        origin=LyricsOrigin.CACHE,
        cache_state=LyricsCacheState.FROM_CACHE,
    )

    def apply(result: LyricsSearchResult, _track: TrackMetadata) -> bool:
        nonlocal active_status
        active_status = LyricsDisplayStatus(
            playback_source="mpris",
            lyrics_source_id=result.artifact.provider,
            lyrics_source_name=result.artifact.provider,
            origin=LyricsOrigin.MANUAL,
            cache_state=LyricsCacheState.MANUAL,
        )
        return True

    controller = LyricsSearchController(
        _Searcher(LyricsSearchResponse((first, second))),
        cache,
        factory,
        on_applied=apply,
        status_provider=lambda: active_status,
    )
    query = LyricsSearchQuery("Song", "Artist", "Album", 180.0)
    controller.open(Config(), query, active_status)
    assert factory.status is active_status

    controller.search(query)
    await asyncio.wait_for(factory.dialog.search_finished.wait(), timeout=1.0)
    controller.select(first)
    await asyncio.wait_for(factory.dialog.apply_finished.wait(), timeout=1.0)
    assert factory.dialog.status.lyrics_source_id == "netease"
    assert factory.dialog.status.cache_state is LyricsCacheState.MANUAL

    factory.dialog.apply_finished.clear()
    controller.select(second)
    await asyncio.wait_for(factory.dialog.apply_finished.wait(), timeout=1.0)
    assert factory.dialog.status.lyrics_source_id == "lrclib"
    assert [artifact.provider for artifact, _mode in cache.writes] == ["netease", "lrclib"]
    assert all(mode is LyricsCacheMode.MANUAL for _artifact_value, mode in cache.writes)
    assert [result.status for result, displayed in factory.dialog.apply_results] == [
        CacheWriteStatus.CREATED,
        CacheWriteStatus.UPDATED,
    ]
    assert all(displayed for _result, displayed in factory.dialog.apply_results)

    await controller.stop()

async def test_search_controller_reopens_after_real_dialog_closes(qapp) -> None:
    factory = _QtFactory(_ordinary_window_factory)
    status = LyricsDisplayStatus()
    controller = LyricsSearchController(
        _Searcher(LyricsSearchResponse(())),
        _Cache(),
        factory,
        on_applied=lambda _result, _track: True,
        status_provider=lambda: status,
    )
    query = LyricsSearchQuery("Song", "Artist")

    controller.open(Config(), query, status)
    first = factory.dialogs[0]
    close_button = first.findChild(QPushButton, "dialogCloseButton")
    assert close_button is not None
    close_button.click()
    qapp.processEvents()
    controller.open(Config(), query, status)

    assert len(factory.dialogs) == 2
    title_close_button = factory.dialogs[1].findChild(QPushButton, "closeButton")
    assert title_close_button is not None
    title_close_button.click()
    qapp.processEvents()
    controller.open(Config(), query, status)

    assert len(factory.dialogs) == 3
    await controller.stop()
    qapp.processEvents()

async def test_search_controller_cancels_closed_dialog_work_before_reopening() -> None:
    result = LyricsSearchResult.from_artifact(_artifact("netease", "1", "result"))
    searcher = _BlockingSearcher(LyricsSearchResponse((result,)))
    factory = _ReopeningFactory()
    controller = LyricsSearchController(
        searcher,
        _Cache(),
        factory,
        on_applied=lambda _result, _track: True,
        status_provider=LyricsDisplayStatus,
    )
    query = LyricsSearchQuery("Song", "Artist")

    controller.open(Config(), query, LyricsDisplayStatus())
    first = factory.dialogs[0]
    controller.search(query)
    await asyncio.wait_for(searcher.started.wait(), timeout=1.0)

    first.close()
    await asyncio.wait_for(searcher.cancelled.wait(), timeout=1.0)
    controller.open(Config(), query, LyricsDisplayStatus())
    second = factory.dialogs[1]
    searcher.release.set()
    controller.search(query)
    await asyncio.wait_for(second.search_finished.wait(), timeout=1.0)

    assert second.results == (result,)
    await controller.stop()

def test_a_failed_selection_reports_in_the_readers_language(qapp):
    from kotonoha.strings.search import SEARCH_STRINGS

    # show_error() takes a strings key, and an unknown key resolves to itself. Two
    # call sites passed English sentences, so those two failures stayed English in
    # every locale while every other one translated.
    keys = {"search.error.result_gone", "search.error.track_gone"}
    assert keys <= set(SEARCH_STRINGS)
    for key in keys:
        assert set(SEARCH_STRINGS[key]) >= {"en", "zh-Hans", "zh-Hant", "ja"}

    import ast

    module = Path(__file__).parent.parent / "src" / "kotonoha" / "app" / "lyrics_search.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))
    spoken = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "show_error"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ]
    assert spoken, "no show_error call was found to check"
    assert all(key.startswith("search.") for key in spoken), spoken

def test_the_timing_label_follows_the_module_that_names_the_encodings(qapp):
    from kotonoha.lyrics.search import LyricsTiming, LyricsVersion

    # The encodings are written in lyrics/search.py; a reader spelling one of them
    # out again cannot be told when a new one arrives, and a new line-timed format
    # would silently fall through to the label meaning "no timing at all".
    assert LyricsVersion("lrc").timing is LyricsTiming.LINE
    assert LyricsVersion("yrc").timing is LyricsTiming.WORD
    assert LyricsVersion("krc").timing is LyricsTiming.WORD
    assert LyricsVersion("lyrics").timing is LyricsTiming.NONE

def test_lifting_a_version_label_leaves_the_rest_of_the_title(qapp):
    from kotonoha.lyrics.title_grammar import title_without_version_labels

    # base_title() drops every bracketed group, which is right for matching and
    # wrong for display: a production credit is not a version, and the row showed
    # only "Realize" while marking nothing but the broadcast edit.
    assert title_without_version_labels("Realize (Prod. by X) (TV Size)") == "Realize (Prod. by X)"
    assert title_without_version_labels("Realize (TV Size)") == "Realize"
    # A title that is nothing but a version group still has to say something.
    assert title_without_version_labels("(TV Size)") == "(TV Size)"

def test_a_search_before_the_service_started_reports_a_key(qapp):
    import pytest

    from kotonoha.lyrics.search import LyricsSearchError, LyricsSearchService

    service = LyricsSearchService({}, lambda: cast("Any", None))
    with pytest.raises(LyricsSearchError) as raised:
        asyncio.run(service.search(LyricsSearchQuery("Song", "Artist"), ("netease",)))

    # The dialog reporting this is localized and resolves an unknown key to
    # itself, so a sentence written here arrives in English in every locale.
    assert raised.value.reason_key.startswith("search.")

def test_applying_settings_rethemes_the_window_that_is_open(qapp):
    from kotonoha.app.lyrics_search import LyricsSearchController
    from kotonoha.config import Config, ThemeMode

    factory = _Factory()
    themes = factory.dialog.themes
    controller = LyricsSearchController(
        _Searcher(LyricsSearchResponse(())),
        _Cache(),
        factory,
        on_applied=lambda result, track: True,
        status_provider=LyricsDisplayStatus,
    )

    # No window open: nothing to retheme, and nothing to fail on either.
    controller.retheme(Config(theme=ThemeMode.LIGHT))
    assert themes == []

    controller.open(Config(), LyricsSearchQuery("Song", "Artist"), LyricsDisplayStatus())
    controller.retheme(Config(theme=ThemeMode.LIGHT))

    # The controller owns the open window; nothing else can reach it.
    assert themes == [str(ThemeMode.LIGHT)]
