import asyncio
from threading import Event

import pytest

from kotonoha.async_worker import BlockingCallRunner


async def _wait_for_thread_event(event: Event, timeout: float = 1.0) -> None:
    """Observe a worker event without using another executor-backed future."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not event.is_set():
        remaining = deadline - loop.time()
        if remaining <= 0.0:
            raise AssertionError("worker event was not observed before the deadline")
        await asyncio.sleep(min(0.01, remaining))


async def test_runner_timeout_does_not_claim_a_running_call_was_cancelled():
    runner = BlockingCallRunner("test-blocking-call")
    started = Event()
    released = Event()
    finished = Event()

    def blocking_call() -> str:
        started.set()
        released.wait()
        finished.set()
        return "finished"

    wait_task = asyncio.create_task(runner.run_with_timeout(0.05, blocking_call))
    await _wait_for_thread_event(started)
    with pytest.raises(TimeoutError):
        await wait_task

    released.set()
    await _wait_for_thread_event(finished)
    runner.close()


async def test_runner_close_is_idempotent_and_rejects_new_calls():
    runner = BlockingCallRunner("test-blocking-call")

    runner.close()
    runner.close()

    with pytest.raises(RuntimeError, match="closed"):
        await runner.run(lambda: None)
