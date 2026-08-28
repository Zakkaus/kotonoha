import asyncio

import pytest

from kotonoha.app.lifecycle import TaskSupervisor


def test_closed_supervisor_closes_a_task_coroutine_it_rejects() -> None:
    async def work() -> None:
        await asyncio.sleep(0)

    supervisor = TaskSupervisor("test")
    supervisor.close()
    coroutine = work()

    with pytest.raises(RuntimeError, match="closed"):
        supervisor.create(coroutine, name="rejected")

    assert coroutine.cr_frame is None
