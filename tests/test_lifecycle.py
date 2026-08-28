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


@pytest.mark.asyncio
async def test_wait_keeps_owned_tasks_alive_when_the_waiter_is_cancelled() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def work() -> None:
        started.set()
        await release.wait()
        finished.set()

    supervisor = TaskSupervisor("test")
    supervisor.create(work(), name="owned-work")
    wait_task = asyncio.create_task(supervisor.wait())
    await started.wait()

    wait_task.cancel()
    await asyncio.sleep(0)
    assert not wait_task.done()
    assert not finished.is_set()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await wait_task
    assert finished.is_set()
    supervisor.close()
