import asyncio
from collections.abc import Callable
from dataclasses import replace

import pytest

from kotonoha.app.config_service import ConfigPersistenceState, ConfigService
from kotonoha.async_worker import BlockingCallRunner
from kotonoha.config import Config, ThemeMode


class MemoryConfigWriter:
    """Capture persisted models without exposing a filesystem in service tests."""

    def __init__(self) -> None:
        self.saved: list[Config] = []

    def save(self, config: Config) -> None:
        self.saved.append(config)


class FailingConfigWriter(MemoryConfigWriter):
    """Fail a configured number of writes so persistence state can be observed."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures

    def save(self, config: Config) -> None:
        if self.failures > 0:
            self.failures -= 1
            raise OSError("test write failed")
        super().save(config)


class ControlledConfigWorker:
    """Hold one async worker call so service cancellation can be observed."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = False

    async def run(
        self,
        function: Callable[..., object],
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        self.started.set()
        await self.release.wait()
        return function(*args, **kwargs)

    def close(self) -> None:
        self.closed = True

    def reopen(self) -> None:
        self.closed = False


@pytest.mark.asyncio
async def test_persists_latest_validated_configuration_with_cider_token() -> None:
    writer = MemoryConfigWriter()
    service = ConfigService(
        Config(),
        writer=writer,
        worker=BlockingCallRunner("test-config-service"),
    )

    service.apply_settings(Config(cider_api_token="secret-token"), frozenset({"cider_api_token"}))
    service.set_passthrough(True)

    await service.close()

    assert service.config.passthrough is True
    assert service.config.cider_api_token == "secret-token"
    assert len(writer.saved) == 1
    assert writer.saved[0].passthrough is True
    assert writer.saved[0].cider_api_token == "secret-token"


@pytest.mark.asyncio
async def test_close_is_idempotent_and_rejects_later_mutations() -> None:
    service = ConfigService(
        Config(),
        writer=MemoryConfigWriter(),
        worker=BlockingCallRunner("test-config-service"),
    )

    await service.close()
    await service.close()

    with pytest.raises(RuntimeError, match="closed"):
        service.set_passthrough(True)


@pytest.mark.asyncio
async def test_config_property_is_detached_from_service_owned_state() -> None:
    service = ConfigService(
        Config(),
        writer=MemoryConfigWriter(),
        worker=BlockingCallRunner("test-config-service"),
    )

    exposed = service.config
    exposed.passthrough = True

    assert service.config.passthrough is False
    await service.close()


@pytest.mark.asyncio
async def test_persistence_failure_is_observable_and_can_be_retried() -> None:
    writer = FailingConfigWriter(failures=1)
    service = ConfigService(
        Config(),
        writer=writer,
        worker=BlockingCallRunner("test-config-service"),
    )

    service.set_passthrough(True)
    await service.flush()

    assert service.persistence_status.state is ConfigPersistenceState.FAILED
    assert service.persistence_status.error == "test write failed"
    assert writer.saved == []

    service.retry_persistence()
    await service.flush()

    assert service.persistence_status.state is ConfigPersistenceState.IDLE
    assert service.persistence_status.error is None
    assert len(writer.saved) == 1
    await service.close()


@pytest.mark.asyncio
async def test_apply_settings_preserves_runtime_changes_made_while_form_was_open() -> None:
    writer = MemoryConfigWriter()
    service = ConfigService(
        Config(margin_edge=32, margin_x=4, passthrough=False),
        writer=writer,
        worker=BlockingCallRunner("test-config-service"),
    )
    opened_config = Config.from_dict(service.config.to_dict())

    service.set_passthrough(True)
    service.set_position(96, 8, "HDMI-A-1", 1920, 1080)
    submitted_config = replace(opened_config, theme=ThemeMode.DARK)

    applied = service.apply_settings(submitted_config, frozenset({"theme"}))

    assert applied.theme is ThemeMode.DARK
    assert applied.passthrough is True
    assert applied.margin_edge == 96
    assert applied.margin_x == 8
    assert applied.screen_name == "HDMI-A-1"
    await service.close()


@pytest.mark.asyncio
async def test_apply_settings_rejects_fields_outside_the_settings_owner() -> None:
    service = ConfigService(
        Config(),
        writer=MemoryConfigWriter(),
        worker=BlockingCallRunner("test-config-service"),
    )

    with pytest.raises(ValueError, match="track_offsets"):
        service.apply_settings(Config(), frozenset({"track_offsets"}))

    await service.close()


@pytest.mark.asyncio
async def test_cancelled_flush_does_not_cancel_the_owned_save() -> None:
    writer = MemoryConfigWriter()
    worker = ControlledConfigWorker()
    service = ConfigService(
        Config(),
        writer=writer,
        worker=worker,
    )
    service.set_passthrough(True)
    await worker.started.wait()

    flush_task = asyncio.create_task(service.flush())
    flush_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await flush_task

    worker.release.set()
    await service.flush()
    assert service.persistence_status.state is ConfigPersistenceState.IDLE
    assert writer.saved[-1].passthrough is True
    await service.close()


@pytest.mark.asyncio
async def test_cancelled_close_finishes_the_owned_save_before_releasing_worker() -> None:
    writer = MemoryConfigWriter()
    worker = ControlledConfigWorker()
    service = ConfigService(
        Config(),
        writer=writer,
        worker=worker,
    )
    service.set_passthrough(True)
    await worker.started.wait()

    close_task = asyncio.create_task(service.close())
    await asyncio.sleep(0)
    close_task.cancel()
    worker.release.set()
    with pytest.raises(asyncio.CancelledError):
        await close_task

    assert service.persistence_status.state is ConfigPersistenceState.IDLE
    assert writer.saved[-1].passthrough is True
    assert worker.closed is True
    await service.close()
