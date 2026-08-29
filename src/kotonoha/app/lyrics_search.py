"""Application workflow for manually selecting lyrics from provider search results."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Protocol

from ..config import Config
from ..display.models import LyricsDisplayStatus
from ..lyrics.artifact import LyricsArtifact
from ..lyrics.cache import CacheWriteResult, LyricsCacheError, LyricsCacheMode
from ..lyrics.match import TrackMetadata
from ..lyrics.search import LyricsSearchError, LyricsSearchPort, LyricsSearchQuery, LyricsSearchResult
from .intents import SearchLyrics, SelectLyrics
from .lifecycle import TaskSupervisor
from .settings_port import LyricsSearchDialogFactory, LyricsSearchDialogPort

logger = logging.getLogger(__name__)


class LyricsCacheWritePort(Protocol):
    """Explicit cache-write capability owned by manual lyric selection."""

    async def upsert(
        self,
        artifact: LyricsArtifact,
        *,
        mode: LyricsCacheMode = LyricsCacheMode.MANUAL,
    ) -> CacheWriteResult:
        """Create or replace one validated lyric artifact."""
        ...


class LyricsSearchController:
    """Own the modeless search window and its cancellable search/write tasks."""

    def __init__(
        self,
        searcher: LyricsSearchPort,
        cache: LyricsCacheWritePort,
        factory: LyricsSearchDialogFactory,
        on_applied: Callable[[LyricsSearchResult, TrackMetadata], bool],
        status_provider: Callable[[], LyricsDisplayStatus],
    ) -> None:
        """Create a workflow from independent search, cache, display, and UI ports."""
        self._searcher = searcher
        self._cache = cache
        self._factory = factory
        self._on_applied = on_applied
        self._status_provider = status_provider
        self._tasks = TaskSupervisor("lyrics-search")
        self._dialog: LyricsSearchDialogPort | None = None
        self._search_task: asyncio.Task[None] | None = None
        self._apply_task: asyncio.Task[None] | None = None
        self._search_owner: LyricsSearchDialogPort | None = None
        self._apply_owner: LyricsSearchDialogPort | None = None
        self._current_track: TrackMetadata | None = None
        self._sources: tuple[str, ...] = ()
        self._results: tuple[LyricsSearchResult, ...] = ()
        self._generation = 0
        self._closed = False

    def open(self, config: Config, query: LyricsSearchQuery, status: LyricsDisplayStatus) -> None:
        """Open or focus the one search window owned by this workflow."""
        if self._closed:
            return
        dialog = self._dialog
        if dialog is not None:
            dialog.raise_()
            dialog.activateWindow()
            return
        self._sources = tuple(config.lyrics_sources)
        self._current_track = query.track_metadata()
        self._results = ()
        dialog = self._factory.create(config, query, status)
        dialog.intent_requested.connect(self._handle_intent)
        dialog.finished.connect(self._clear_dialog)
        self._dialog = dialog
        dialog.show()

    def search(self, query: LyricsSearchQuery) -> None:
        """Schedule a provider search and discard responses from older generations."""
        dialog = self._dialog
        if dialog is None or self._operation_active(dialog):
            return
        previous = self._search_task
        if previous is not None and not previous.done():
            previous.cancel()
        self._results = ()
        self._generation += 1
        generation = self._generation
        dialog.set_busy(True)
        task = self._tasks.create(
            self._search_async(dialog, query, generation),
            name="kotonoha-search-lyrics",
        )
        self._search_task = task
        self._search_owner = dialog
        task.add_done_callback(self._search_finished)

    def select(self, result: LyricsSearchResult) -> None:
        """Persist one result only when it belongs to the current result set."""
        dialog = self._dialog
        if dialog is None or self._operation_active(dialog):
            return
        if result not in self._results:
            dialog.show_error("The selected lyric result is no longer available")
            return
        current_track = self._current_track
        if current_track is None:
            dialog.show_error("The current track is no longer available")
            return
        previous = self._apply_task
        if previous is not None and not previous.done():
            previous.cancel()
        dialog.set_current_status(self._status_provider())
        dialog.set_busy(True)
        task = self._tasks.create(
            self._apply_async(dialog, result, current_track),
            name="kotonoha-apply-lyrics-selection",
        )
        self._apply_task = task
        self._apply_owner = dialog
        task.add_done_callback(self._apply_finished)

    async def stop(self) -> None:
        """Close the window, cancel active work, and reject future commands."""
        if self._closed:
            return
        dialog = self._dialog
        if dialog is not None:
            try:
                dialog.close()
            except (OSError, RuntimeError) as exc:
                logger.warning("Could not close lyrics search window: %s", exc)
            finally:
                self._dialog = None
        for task in (self._search_task, self._apply_task):
            if task is not None and not task.done():
                task.cancel()
        await self._tasks.wait()
        self._search_task = None
        self._apply_task = None
        self._search_owner = None
        self._apply_owner = None
        self._tasks.close()
        self._closed = True

    def _operation_active(self, dialog: LyricsSearchDialogPort) -> bool:
        """Return whether a search or explicit cache write owns the dialog."""
        return any(
            task is not None and not task.done() and owner is dialog
            for task, owner in (
                (self._search_task, self._search_owner),
                (self._apply_task, self._apply_owner),
            )
        )

    def _handle_intent(self, intent: object) -> None:
        """Route dialog commands back to this application workflow owner."""
        if isinstance(intent, SearchLyrics):
            self.search(intent.query)
        elif isinstance(intent, SelectLyrics):
            self.select(intent.result)

    def _clear_dialog(self, _result: int | None = None) -> None:
        """End the dialog session and cancel work that can no longer update it."""
        dialog = self._dialog
        self._dialog = None
        if dialog is None:
            return
        for task, owner in (
            (self._search_task, self._search_owner),
            (self._apply_task, self._apply_owner),
        ):
            if task is not None and not task.done() and owner is dialog:
                task.cancel()

    async def _search_async(
        self,
        dialog: LyricsSearchDialogPort,
        query: LyricsSearchQuery,
        generation: int,
    ) -> None:
        """Run one provider search and publish only its current response."""
        response = await self._searcher.search(query, self._sources)
        if self._dialog is dialog and generation == self._generation:
            self._results = response.results
            dialog.set_current_status(self._status_provider())
            dialog.set_results(query, response)
            dialog.set_busy(False)

    def _search_finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        current = self._search_task is task
        if current:
            self._search_task = None
            self._search_owner = None
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except (LyricsSearchError, RuntimeError, TimeoutError) as exc:
            if current and self._dialog is not None:
                self._dialog.set_busy(False)
                self._dialog.show_error(f"Search failed: {exc}")

    async def _apply_async(
        self,
        dialog: LyricsSearchDialogPort,
        result: LyricsSearchResult,
        current_track: TrackMetadata,
    ) -> None:
        """Write and immediately display the selected artifact as a manual result."""
        write_result = await self._cache.upsert(result.artifact, mode=LyricsCacheMode.MANUAL)
        displayed = self._on_applied(result, current_track)
        if self._dialog is dialog:
            dialog.set_current_status(self._status_provider())
            dialog.show_apply_result(write_result, displayed)
            dialog.set_busy(False)

    def _apply_finished(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        current = self._apply_task is task
        if current:
            self._apply_task = None
            self._apply_owner = None
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except (LyricsCacheError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
            if current and self._dialog is not None:
                self._dialog.set_busy(False)
                self._dialog.show_error(f"Apply failed: {exc}")


__all__ = ["LyricsCacheWritePort", "LyricsSearchController"]
