"""The single concrete object-graph composition root for Kotonoha."""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import QApplication

from ..async_worker import BlockingCallRunner, BlockingWorkerPort
from ..config import Config, ConfigStore, clamp_port
from ..display.presentation import DisplayEngine
from ..display.timeline import TimelineEngine
from ..i18n import resolve_translation_language
from ..lyrics import kugou, lrclib, netease, qqmusic
from ..lyrics.cache import LyricsCache
from ..lyrics.catalog import LyricsSourceCatalog
from ..lyrics.live_source import LiveLyricsSource
from ..lyrics.network_sources import NetworkLyricsSource
from ..lyrics.resolver import LyricsResolver
from ..lyrics.sources import EmbeddedLyricsSource, LocalLyricsSource, SidecarLyricsSource
from ..platform import (
    DefaultOverlayPlatformFactory,
    LayerShellController,
    OverlayPlatformFactory,
    default_package_dir,
)
from ..platform.restart import QProcessRestartLauncher
from ..players import PlayerInfo
from ..providers.cider_api import CiderApiProvider
from ..providers.cider_client import CiderApiClient
from ..providers.mpris import MprisProvider
from ..providers.mpris_adapter import MprisPlaybackAdapter
from ..providers.mpris_session import MprisSession
from ..receiver import AdapterReceiver
from ..strings import Translator
from ..tray import KotonohaTray, load_icon
from ..ui.overlay import LyricsOverlay
from ..ui.overlay.publisher import QtDisplayPublisher
from ..ui.overlay.state import LyricsState
from ..ui.settings.dialog import SettingsDialog
from .application_controller import AppController
from .components import ApplicationComponents, RestartLauncher
from .config_service import ConfigService, ConfigWriter
from .display_coordinator import DisplayCoordinator
from .services import RuntimeConfigApplier, display_options
from .settings_port import SettingsDialogFactory
from .source_gate import SourceOwnershipCoordinator

logger = logging.getLogger(__name__)


class _QtRuntimePort:
    """Adapt Qt application state to the application runtime-config port."""

    def __init__(self, app: QApplication, translator: Translator) -> None:
        self._app = app
        self._translator = translator

    def set_language(self, value: str | None) -> None:
        self._translator.set_language(value)

    def set_window_icon(self, icon_name: str, accent: str) -> None:
        self._app.setWindowIcon(load_icon(icon_name, accent=accent))


def apply_cli_port(config: Config, cli_port: int | None) -> Config:
    """Return a clamped configuration with the optional process port override."""
    normalized = config.clamped()
    if cli_port is None:
        return normalized
    clamped = clamp_port(cli_port)
    if clamped != cli_port:
        logger.warning("CLI --port %d is out of range 1..65535; using %d", cli_port, clamped)
    normalized.port = clamped
    return normalized


class _QtSettingsDialogFactory:
    """Adapt the Qt Settings dialog to the application-facing factory contract."""

    def __init__(self, regular_window_factory: OverlayPlatformFactory, translator: Translator) -> None:
        self._regular_window_factory = regular_window_factory
        self._translator = translator

    def create(self, config: Config, players: list[PlayerInfo]) -> SettingsDialog:
        return SettingsDialog(
            config,
            players=players,
            platform_factory=self._regular_window_factory,
            translator=self._translator,
        )


class ApplicationComposition:
    """Build one application graph from explicit external-boundary dependencies."""

    def __init__(
        self,
        app: QApplication,
        config: Config,
        *,
        config_writer: ConfigWriter,
        config_worker: BlockingWorkerPort,
        restart_launcher: RestartLauncher,
    ) -> None:
        self._app = app
        self._config = config.clamped()
        self._config_writer = config_writer
        self._config_worker = config_worker
        self._restart_launcher = restart_launcher
        self._controller: AppController | None = None

    @classmethod
    async def production(
        cls,
        app: QApplication,
        config: Config | None = None,
        *,
        cli_port: int | None = None,
    ) -> ApplicationComposition:
        """Create the production graph with concrete process-boundary adapters.

        ``config`` is an explicit test/integration seam. Normal startup loads the
        model through the same ``ConfigStore`` that the ConfigService will later
        use for persistence, so there is one configuration boundary and owner.
        """
        config_store = ConfigStore(Config)
        config_worker = BlockingCallRunner("kotonoha-config")
        worker_transferred = False
        try:
            initial_config = config if config is not None else await config_worker.run(config_store.load)
            composition = cls(
                app,
                apply_cli_port(initial_config, cli_port),
                config_writer=config_store,
                config_worker=config_worker,
                restart_launcher=QProcessRestartLauncher(),
            )
            worker_transferred = True
            return composition
        finally:
            if not worker_transferred:
                config_worker.close()

    def build(self) -> AppController:
        """Build the graph once and return its application lifecycle owner."""
        if self._controller is not None:
            return self._controller

        local_worker = BlockingCallRunner("kotonoha-local-lyrics")
        cache_worker = BlockingCallRunner("kotonoha-lyrics-cache")
        try:
            controller = self._build_unchecked(local_worker, cache_worker)
        except BaseException:
            # Construction happens before AppController owns the graph, so the
            # composition root must release every worker it allocated itself.
            # This is deliberately a cleanup-only catch: the original build
            # failure is re-raised after the resources are released.
            self._close_build_worker(local_worker, "local lyrics")
            self._close_build_worker(cache_worker, "lyrics cache")
            self._close_build_worker(self._config_worker, "configuration")
            raise
        self._controller = controller
        return controller

    def _build_unchecked(
        self,
        local_worker: BlockingWorkerPort,
        cache_worker: BlockingWorkerPort,
    ) -> AppController:
        """Construct the graph while :meth:`build` owns rollback on failure."""

        config_service = ConfigService(
            self._config,
            writer=self._config_writer,
            worker=self._config_worker,
        )
        config = config_service.config
        translator = Translator(config.ui_language)
        ui_runtime = _QtRuntimePort(self._app, translator)
        ui_runtime.set_language(config.ui_language)
        ui_runtime.set_window_icon(config.window_icon_name, config.accent_start)

        state = LyricsState()
        publisher = QtDisplayPublisher(state)
        display = DisplayCoordinator(
            publisher,
            presenter=DisplayEngine(display_options(config)),
            timeline=TimelineEngine(),
        )

        platform_name = self._app.platformName()
        desktop_value = self._app.property("xdg_current_desktop")
        desktop = desktop_value if isinstance(desktop_value, str) else ""
        layer_shell = LayerShellController(default_package_dir(), platform_name, desktop)
        platform_factory = DefaultOverlayPlatformFactory(
            layer_shell,
            platform_name=platform_name,
            current_desktop=desktop,
        )
        overlay = LyricsOverlay(state, config, platform_factory=platform_factory, translator=translator)

        ownership = SourceOwnershipCoordinator(display_sources=config.display_sources)
        local_source = LocalLyricsSource(
            SidecarLyricsSource(),
            EmbeddedLyricsSource(),
            worker=local_worker,
        )
        lyric_sources = {
            "netease": NetworkLyricsSource(
                "netease",
                netease.fetch_artifact,
                netease.parse_payload,
                exact_fetch=netease.fetch_artifact_for_song_id,
            ),
            "qqmusic": NetworkLyricsSource(
                "qqmusic",
                qqmusic.fetch_artifact,
                qqmusic.parse_payload,
                exact_fetch=qqmusic.fetch_artifact_for_song_id,
            ),
            "lrclib": NetworkLyricsSource("lrclib", lrclib.fetch_artifact, lrclib.parse_payload),
            "kugou": NetworkLyricsSource("kugou", kugou.fetch_artifact, kugou.parse_payload),
        }
        catalog = LyricsSourceCatalog(
            lyric_sources,
            live_source=LiveLyricsSource(ownership),
            local_source=local_source,
        )
        resolver = LyricsResolver(
            catalog=catalog,
            cache=LyricsCache(worker=cache_worker),
            cache_enabled=config.cache_enabled,
        )
        receiver = AdapterReceiver(display, port=config.port, ownership=ownership)
        cider = CiderApiProvider(
            display=display,
            ownership=ownership,
            client=CiderApiClient(token=config.cider_api_token),
            translation_language=resolve_translation_language(config.translation_language),
            enabled="cider" in config.lyrics_sources,
        )
        mpris = MprisProvider(
            display,
            lyrics_sources=config.lyrics_sources,
            ownership=ownership,
            resolver=resolver,
            playback_adapter=MprisPlaybackAdapter(),
            playback_session=MprisSession(),
        )
        mpris.set_player_lock(config.player_lock)
        mpris.set_cache_enabled(config.cache_enabled)
        mpris.set_prefer_best(config.prefer_best_lyrics)
        mpris.set_fuzzy(config.fuzzy_match)

        tray = KotonohaTray(
            icon_name=config.icon_name,
            accent=config.accent_start,
            passthrough=config.passthrough,
            on_toggle_passthrough=None,
            on_open_settings=None,
            on_quit=self._app.quit,
            translator=translator,
        )
        settings_factory: SettingsDialogFactory = _QtSettingsDialogFactory(
            platform_factory.for_regular_window,
            translator,
        )
        runtime_config = RuntimeConfigApplier(
            ui_runtime,
            display,
            overlay,
            tray,
            mpris,
            cider,
            ownership,
        )
        components = ApplicationComponents(
            config_service=config_service,
            restart_launcher=self._restart_launcher,
            display=display,
            overlay=overlay,
            settings_factory=settings_factory,
            receiver=receiver,
            cider=cider,
            mpris=mpris,
            tray=tray,
            runtime_config=runtime_config,
        )
        controller = AppController(self._app, components)
        # The tray callbacks are bound to the controller after construction so the
        # graph remains explicit without giving the tray a controller dependency.
        tray.set_action_handlers(
            on_toggle_passthrough=controller.on_toggle_passthrough,
            on_open_settings=controller.open_settings,
        )
        return controller

    @staticmethod
    def _close_build_worker(worker: BlockingWorkerPort, name: str) -> None:
        """Close one pre-controller worker without masking the construction error."""
        try:
            worker.close()
        except (OSError, RuntimeError) as exc:
            logger.warning("Could not roll back %s worker: %s", name, exc)


__all__ = ["ApplicationComposition", "apply_cli_port"]
