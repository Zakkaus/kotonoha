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


@pytest.mark.asyncio
async def test_persists_latest_validated_configuration_without_runtime_token() -> None:
    writer = MemoryConfigWriter()
    service = ConfigService(
        Config(),
        writer=writer,
        worker=BlockingCallRunner("test-config-service"),
    )

    service.set_runtime_token("secret-token")
    service.set_passthrough(True)
    service.set_track_offset("song", 123)

    await service.close()

    assert service.config.passthrough is True
    assert service.config.track_offsets == {"song": 123}
    assert service.config.cider_api_token == "secret-token"
    assert len(writer.saved) == 1
    assert writer.saved[0].passthrough is True
    assert writer.saved[0].track_offsets == {"song": 123}
    assert writer.saved[0].cider_api_token == ""


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
        Config(margin_edge=32, margin_x=4, passthrough=False, track_offsets={"song": 20}),
        writer=writer,
        worker=BlockingCallRunner("test-config-service"),
    )
    opened_config = Config.from_dict(service.config.to_dict())

    service.set_passthrough(True)
    service.set_position(96, 8, "HDMI-A-1", 1920, 1080)
    service.set_track_offset("song", 120)
    submitted_config = replace(opened_config, theme=ThemeMode.DARK)

    applied = service.apply_settings(submitted_config, frozenset({"theme"}))

    assert applied.theme is ThemeMode.DARK
    assert applied.passthrough is True
    assert applied.margin_edge == 96
    assert applied.margin_x == 8
    assert applied.screen_name == "HDMI-A-1"
    assert applied.track_offsets == {"song": 120}
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
