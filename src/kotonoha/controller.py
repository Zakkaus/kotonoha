"""Application controller: owns the long-lived objects and wires interactions.

Separated from main.py so the wiring is import-testable without spinning up a
real Qt event loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys

from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import QApplication

from .async_worker import BlockingCallRunner
from .config import Config, save_config
from .display.coordinator import DisplayCoordinator
from .display.models import (
    DisplayOptions,
    DisplayScript,
    InterludeCountdown,
    InterludeMarkerStyle,
)
from .i18n import resolve_translation_language
from .lyrics.cache import LyricsCacheError
from .lyrics.catalog import LyricsSourceCatalog
from .lyrics.ownership import SourceOwnershipCoordinator
from .lyrics.resolver import LyricsResolver
from .overlay import LyricsOverlay
from .platform import (
    DefaultOverlayPlatformFactory,
    LayerShellController,
    default_package_dir,
)
from .providers.cider_api import CiderApiProvider
from .providers.cider_client import CiderApiClient
from .providers.cider_credentials import CiderApiTokenStore, KeyringCiderApiTokenStore
from .providers.mpris import MprisProvider
from .providers.mpris_session import MprisSessionError
from .receiver import AdapterReceiver
from .settings_dialog import SettingsDialog
from .state import LyricsState
from .strings import set_language
from .tray import KotonohaTray, load_icon

logger = logging.getLogger(__name__)


def _display_options(config: Config) -> DisplayOptions:
    """Translate persisted settings into an immutable display-domain snapshot."""
    return DisplayOptions(
        lead_ms=config.lead_ms,
        track_offsets_ms=dict(config.track_offsets),
        lyrics_script=DisplayScript(config.lyrics_script.value),
        interlude_style=InterludeMarkerStyle(config.interlude_style.value),
        interlude_countdown=InterludeCountdown(config.interlude_countdown.value),
    )


class AppController:
    def __init__(
        self,
        app: QApplication,
        config: Config,
        *,
        cider_token_store: CiderApiTokenStore | None = None,
    ) -> None:
        self._app = app
        self._cider_token_store = cider_token_store if cider_token_store is not None else KeyringCiderApiTokenStore()
        self._cider_token_worker = BlockingCallRunner("kotonoha-cider-token")
        self._cider_token_tasks: set[asyncio.Task[None]] = set()
        self._cider_token_save_lock = asyncio.Lock()
        self._clear_cache_task: asyncio.Task[None] | None = None
        cli_port = app.property("cli_port")
        config = config.clamped()
        if isinstance(cli_port, int):
            # Clamp the CLI port too: argparse accepts any int, and an out-of-range
            # value (e.g. --port 70000 or -1) would otherwise reach socket.bind()
            # and raise OverflowError — which is not an OSError, so the receiver's
            # and controller's `except OSError` would miss it and startup crashes.
            clamped_port = max(1, min(65535, cli_port))
            if clamped_port != cli_port:
                logger.warning("CLI --port %d is out of range 1..65535; using %d", cli_port, clamped_port)
            config.port = clamped_port
        self._config = config
        set_language(config.ui_language)  # before any UI strings are created
        self._app.setWindowIcon(load_icon(config.window_icon_name, accent=config.accent_start))

        self._state = LyricsState()
        self._display = DisplayCoordinator(self._state, options=_display_options(config))
        platform_name = app.platformName()
        desktop = str(app.property("xdg_current_desktop") or "")
        layer_shell = LayerShellController(default_package_dir(), platform_name, desktop)
        self._platform_factory = DefaultOverlayPlatformFactory(
            layer_shell,
            platform_name=platform_name,
            current_desktop=desktop,
        )
        self._overlay = LyricsOverlay(self._state, config, platform_factory=self._platform_factory)
        ownership = SourceOwnershipCoordinator()
        resolver = LyricsResolver(catalog=LyricsSourceCatalog.default(ownership), cache_enabled=config.cache_enabled)
        self._receiver = AdapterReceiver(self._display, port=config.port, ownership=ownership)
        self._cider = CiderApiProvider(
            display=self._display,
            ownership=ownership,
            client=CiderApiClient(token=config.cider_api_token),
            translation_language=resolve_translation_language(config.translation_language),
            enabled="cider" in config.lyrics_sources,
        )
        self._mpris = MprisProvider(
            self._display,
            lyrics_sources=config.lyrics_sources,
            ownership=ownership,
            resolver=resolver,
        )
        self._mpris.set_player_lock(config.player_lock)
        self._mpris.set_cache_enabled(config.cache_enabled)
        self._mpris.set_prefer_best(config.prefer_best_lyrics)
        self._mpris.set_fuzzy(config.fuzzy_match)
        self._settings_dialog: SettingsDialog | None = None
        self._settings_open_task: asyncio.Task[None] | None = None

        self._tray = KotonohaTray(
            icon_name=config.icon_name,
            accent=config.accent_start,
            passthrough=config.passthrough,
            on_toggle_passthrough=self._on_toggle_passthrough,
            on_open_settings=self._open_settings,
            on_quit=self._app.quit,
        )

        self._overlay.passthrough_toggle_requested.connect(self._toggle_passthrough)
        self._overlay.settings_requested.connect(self._open_settings)
        self._overlay.position_changed.connect(self._on_position_changed)
        self._overlay.track_offset_changed.connect(self._on_track_offset_changed)

    async def start(self) -> None:
        await self._load_cider_token()
        # Promote to a layer surface BEFORE show(): once the window is mapped as a
        # normal xdg surface, LayerShellQt can no longer convert it.
        self._overlay.activate_layer_shell()
        self._overlay.show()
        self._tray.show()
        await self._display.start()
        # The generic adapter receiver is optional: a port bind failure — a stale
        # instance or double-launch already holding 28745 — must only disable
        # external WS adapters, not take down the overlay/tray.
        try:
            await self._receiver.start()
        except OSError as exc:
            logger.warning("External adapter receiver unavailable: %s", exc)
        try:
            await self._cider.start()
        except OSError as exc:
            logger.warning("Cider API provider unavailable: %s", exc)
        # MPRIS is best-effort: a missing session bus / dbus must not stop the app.
        try:
            await self._mpris.start()
        except (MprisSessionError, OSError) as exc:
            logger.warning("MPRIS provider unavailable: %s", exc)
        logger.info("Kotonoha started on port %d", self._config.port)

    async def stop(self) -> None:
        await self._finish_settings_open()
        if self._settings_dialog is not None:
            self._settings_dialog.close()
            self._settings_dialog = None
        surface_result = self._overlay.shutdown()
        if not surface_result.succeeded:
            logger.warning("Overlay surface shutdown was incomplete: %s", surface_result.reason)
        await self._mpris.stop()
        await self._cider.stop()
        await self._receiver.stop()
        await self._display.stop()
        await self._finish_clear_cache()
        await self._finish_cider_token_save()
        self._cider_token_worker.close()

    async def _finish_settings_open(self) -> None:
        """Cancel and await settings discovery before the controller is closed."""
        task = self._settings_open_task
        self._settings_open_task = None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _load_cider_token(self) -> None:
        """Load the Cider credential off the UI loop before starting the client."""
        try:
            token = await self._cider_token_worker.run(self._cider_token_store.load)
        except (OSError, RuntimeError) as exc:
            logger.warning("Could not load the Cider API token: %s", exc)
            token = self._config.cider_api_token
        self._config.cider_api_token = token
        self._cider.set_token(token)

    async def _save_cider_token(self, token: str) -> None:
        """Persist one settings change through the owned worker task."""
        async with self._cider_token_save_lock:
            await self._cider_token_worker.run(self._cider_token_store.save, token)

    def _schedule_cider_token_save(self, token: str) -> None:
        """Retain the credential write task until it completes or shutdown."""
        task = asyncio.create_task(self._save_cider_token(token))
        self._cider_token_tasks.add(task)
        task.add_done_callback(self._cider_token_save_finished)

    def _cider_token_save_finished(self, task: asyncio.Task[None]) -> None:
        self._cider_token_tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except (OSError, RuntimeError) as exc:
            logger.warning("Could not save the Cider API token: %s", exc)

    async def _finish_cider_token_save(self) -> None:
        tasks = tuple(self._cider_token_tasks)
        if not tasks:
            return
        # Do not cancel to_thread wrappers: the keyring call may still be running
        # after cancellation, and a later token could otherwise be overwritten by
        # an older write. The lock orders writes and gather keeps shutdown owned.
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _finish_clear_cache(self) -> None:
        task = self._clear_cache_task
        if task is None:
            return
        await asyncio.gather(task, return_exceptions=True)
        if self._clear_cache_task is task:
            self._clear_cache_task = None

    # --- passthrough / lock ---

    def _toggle_passthrough(self) -> None:
        self._on_toggle_passthrough(not self._config.passthrough)

    def _on_toggle_passthrough(self, checked: bool) -> None:
        if checked == self._config.passthrough:
            self._overlay.set_passthrough(checked)
            return
        self._overlay.set_passthrough(checked)
        self._tray.set_passthrough_checked(checked)
        self._config.passthrough = checked
        self._persist()

    def _on_position_changed(self, margin_edge: int, margin_x: int, screen_name: str) -> None:
        self._config.margin_edge = margin_edge
        self._config.margin_x = margin_x
        self._config.screen_name = screen_name
        self._persist()

    def _on_track_offset_changed(self, key: str, offset_ms: int) -> None:
        self._config.track_offsets[key] = offset_ms
        self._display.set_options(_display_options(self._config))
        self._persist()

    # --- settings ---

    def _open_settings(self) -> None:
        if self._settings_dialog is not None:
            self._settings_dialog.raise_()
            self._settings_dialog.activateWindow()
            return
        if self._settings_open_task is not None and not self._settings_open_task.done():
            return
        task = asyncio.create_task(self._open_settings_async())
        self._settings_open_task = task

        def finished(done: asyncio.Task[None]) -> None:
            if self._settings_open_task is done:
                self._settings_open_task = None
            try:
                done.result()
            except asyncio.CancelledError:
                return
            except (MprisSessionError, OSError, RuntimeError) as exc:
                logger.warning("Could not open settings: %s", exc)

        task.add_done_callback(finished)

    async def _open_settings_async(self) -> None:
        if self._settings_dialog is not None:
            return
        try:
            players = await self._mpris.available_players()
        except (MprisSessionError, OSError, TimeoutError) as exc:
            logger.debug("MPRIS player discovery failed: %s", exc)
            players = []
        dialog = SettingsDialog(
            self._config,
            players=players,
            # Through the registry, not a hardcoded adapter: the settings window is
            # a window on the same session as the overlay, and pinning Layer Shell
            # here handed an X11 session layer-shell capabilities — it reported no
            # window opacity and dropped its own fade-in.
            platform_factory=self._platform_factory,
        )
        dialog.applied.connect(self._apply_config)
        dialog.clear_cache_requested.connect(self._clear_lyrics_cache)
        dialog.restart_requested.connect(self._restart)
        dialog.finished.connect(self._clear_dialog)
        self._settings_dialog = dialog
        dialog.show()

    def _clear_dialog(self, _result: int | None = None) -> None:
        self._settings_dialog = None

    def _restart(self) -> None:
        # Relaunch via `python -m kotonoha` so it works whether we were started as
        # the `kotonoha` console script or with `-m`, preserving the CLI args, then
        # quit this instance so its shutdown runs cleanly and the port is released.
        started, _pid = QProcess.startDetached(sys.executable, ["-m", "kotonoha", *sys.argv[1:]])
        if not started:
            # Quitting here would leave the user with nothing running: the result
            # was discarded and this instance exited regardless, so a replacement
            # that could not be spawned looked exactly like a successful restart.
            logger.error("Could not start the replacement process; staying up")
            return
        logger.info("Restarting to apply settings")
        self._app.quit()

    def _apply_config(self, config: Config) -> None:
        previous_language = resolve_translation_language(self._config.translation_language)
        previous_token = self._config.cider_api_token
        config.track_offsets = self._config.track_offsets
        self._config = config.clamped()
        self._display.set_options(_display_options(self._config))
        self._overlay.apply_config(self._config)
        # Push new anchor/margins/passthrough through the layer-shell bridge.
        self._overlay.activate_layer_shell()
        self._tray.set_passthrough_checked(self._config.passthrough)
        self._app.setWindowIcon(load_icon(self._config.window_icon_name, accent=self._config.accent_start))
        self._tray.set_icon_name(self._config.icon_name, self._config.accent_start)
        self._mpris.set_lyrics_sources(self._config.lyrics_sources)
        self._cider.set_enabled("cider" in self._config.lyrics_sources)
        self._cider.set_token(self._config.cider_api_token)
        self._mpris.set_player_lock(self._config.player_lock)
        self._mpris.set_cache_enabled(self._config.cache_enabled)
        self._mpris.set_prefer_best(self._config.prefer_best_lyrics)
        self._mpris.set_fuzzy(self._config.fuzzy_match)
        set_language(self._config.ui_language)  # affects newly-opened dialogs; UI restart for the rest

        if self._config.cider_api_token != previous_token:
            self._schedule_cider_token_save(self._config.cider_api_token)

        new_language = resolve_translation_language(self._config.translation_language)
        if new_language != previous_language:
            self._cider.set_translation_language(new_language)

        self._persist()

    def _clear_lyrics_cache(self) -> None:
        if self._clear_cache_task is not None and not self._clear_cache_task.done():
            return
        task = asyncio.create_task(self._mpris.clear_cache())
        self._clear_cache_task = task
        task.add_done_callback(self._clear_lyrics_cache_finished)

    def _clear_lyrics_cache_finished(self, task: asyncio.Task[None]) -> None:
        if self._clear_cache_task is task:
            self._clear_cache_task = None
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except LyricsCacheError as exc:
            logger.warning("Could not clear lyrics cache: %s", exc)

    def _persist(self) -> None:
        try:
            save_config(self._config)
        except OSError as exc:
            logger.warning("Could not save config: %s", exc)

    # --- accessors for tests ---

    @property
    def overlay(self) -> LyricsOverlay:
        return self._overlay

    @property
    def state(self) -> LyricsState:
        return self._state

    @property
    def receiver(self) -> AdapterReceiver:
        return self._receiver
