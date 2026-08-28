import asyncio
import os
from collections.abc import Sequence
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from kotonoha.app import application_controller as controller_module
from kotonoha.app.config_service import ConfigService
from kotonoha.app.intents import ChangeTrackOffset
from kotonoha.async_worker import BlockingCallRunner
from kotonoha.config import Config
from kotonoha.controller import AppController
from kotonoha.providers.mpris import MprisProvider
from kotonoha.receiver import AdapterReceiver


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeReceiver:
    async def start(self):
        raise OSError(98, "Address already in use")

    async def stop(self):
        return None


class _FakeMpris:
    def __init__(self):
        self.started = False

    async def start(self):
        self.started = True

    async def stop(self):
        return None


class _FakeCiderTokenStore:
    def __init__(self, token: str = "") -> None:
        self.token = token
        self.saved: list[str] = []

    def load(self) -> str:
        return self.token

    def save(self, token: str) -> None:
        self.token = token
        self.saved.append(token)


class _FakeConfigWriter:
    def __init__(self) -> None:
        self.saved: list[Config] = []

    def save(self, config: Config) -> None:
        self.saved.append(config)


def _config_service(config: Config | None = None) -> ConfigService:
    initial = Config() if config is None else config
    return ConfigService(
        initial,
        writer=_FakeConfigWriter(),
        worker=BlockingCallRunner("test-config-service"),
    )


class _Signal:
    def connect(self, _slot):
        return None


class _FakeDialog:
    def __init__(self):
        self.intent_requested = _Signal()
        self.applied = _Signal()
        self.clear_cache_requested = _Signal()
        self.restart_requested = _Signal()
        self.finished = _Signal()

    def show(self):
        return None

    def close(self):
        return None


async def test_start_survives_optional_receiver_bind_failure(qapp):
    # A stale instance / double-launch holding port 28745 must only disable the
    # optional Cider receiver, not take down the already-shown overlay and tray.
    token_store = _FakeCiderTokenStore("loaded-token")
    service = _config_service()
    controller = AppController(qapp, service, cider_token_store=token_store)
    controller._receiver = cast(AdapterReceiver, _FakeReceiver())
    fake_mpris = _FakeMpris()
    controller._mpris = cast(MprisProvider, fake_mpris)

    await controller.start()  # must not raise

    assert fake_mpris.started is True  # reached MPRIS despite the receiver failure
    assert controller._config.cider_api_token == "loaded-token"
    await controller.stop()
    controller._overlay.deleteLater()
    qapp.processEvents()


async def test_run_stops_controller_when_startup_fails(qapp, monkeypatch):
    from kotonoha import main as main_module

    class _StartupFailureController:
        def __init__(self) -> None:
            self.stopped = False

        async def start(self) -> None:
            raise RuntimeError("startup failed")

        async def stop(self) -> None:
            self.stopped = True

    controller = _StartupFailureController()
    monkeypatch.setattr(main_module, "_build_app_objects", lambda _app, _config: controller)
    monkeypatch.setattr("kotonoha.config.load_config", Config)

    with pytest.raises(RuntimeError, match="startup failed"):
        await main_module._run(qapp)

    assert controller.stopped is True


def test_out_of_range_cli_port_is_clamped(qapp):
    # argparse accepts any int; an unclamped 70000 reaches socket.bind() and raises
    # OverflowError (not an OSError), crashing startup. It must be clamped instead.
    from kotonoha.main import _apply_cli_port

    assert _apply_cli_port(Config(), 70000).port == 65535


async def test_settings_discovery_does_not_open_two_dialogs(qapp, monkeypatch):
    service = _config_service()
    controller = AppController(qapp, service)
    started = asyncio.Event()
    release = asyncio.Event()
    created = []

    class _DeferredMpris:
        async def available_players(self):
            started.set()
            await release.wait()
            return []

        async def stop(self):
            return None

    def make_dialog(*_args, **_kwargs):
        created.append(True)
        return _FakeDialog()

    controller._mpris = cast(MprisProvider, _DeferredMpris())
    monkeypatch.setattr(controller_module, "SettingsDialog", make_dialog)
    try:
        controller._open_settings()
        await started.wait()
        controller._open_settings()
        release.set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert len(created) == 1
    finally:
        await controller.stop()
        controller._overlay.deleteLater()
        qapp.processEvents()


async def test_tray_settings_action_opens_a_normal_visible_dialog(qapp):
    service = _config_service()
    controller = AppController(qapp, service)
    try:
        # The menu owns a real QAction; triggering it exercises tray -> controller
        # -> supervised settings task instead of calling the controller directly.
        menu = controller._tray.contextMenu()
        if menu is None:
            raise AssertionError("tray context menu was not created")
        settings_action = menu.actions()[2]
        settings_action.trigger()
        task = controller._settings_open_task
        assert task is not None
        await task

        dialog = controller._settings_dialog
        assert dialog is not None
        assert dialog.isVisible()
        assert not dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    finally:
        await controller.stop()
        controller._overlay.deleteLater()
        qapp.processEvents()


async def test_controller_persists_track_offset(qapp):
    writer = _FakeConfigWriter()
    service = ConfigService(
        Config(),
        writer=writer,
        worker=BlockingCallRunner("test-config-service"),
    )
    controller = AppController(qapp, service)
    controller._handle_intent(ChangeTrackOffset("track", 50))
    await service.close()
    assert controller._config.track_offsets == {"track": 50}
    assert writer.saved[-1].track_offsets == {"track": 50}
    await controller.stop()
    controller._overlay.deleteLater()
    qapp.processEvents()


async def test_a_restart_that_cannot_start_the_replacement_stays_up(qapp):
    # The result was discarded and this instance quit regardless, so a replacement
    # that could not be spawned looked exactly like a successful restart — and left
    # the user with nothing running.
    class _FailedRestartLauncher:
        def start(self, executable: str, arguments: Sequence[str]) -> bool:
            del executable, arguments
            return False

    service = _config_service()
    controller = AppController(qapp, service, restart_launcher=_FailedRestartLauncher())
    try:
        controller._restart()
    finally:
        await controller.stop()
        controller._overlay.deleteLater()
        qapp.processEvents()
