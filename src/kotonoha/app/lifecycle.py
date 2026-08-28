"""Application-owned asyncio task supervision."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine

from ..async_task import create_owned_task, wait_for_owned


class TaskSupervisor:
    """Retain task handles and provide an explicit wait boundary for an owner."""

    def __init__(self, name: str) -> None:
        if not name:
            raise ValueError("task supervisor name must not be empty")
        self._name = name
        self._tasks: set[asyncio.Task[None]] = set()
        self._closed = False

    def create(self, coroutine: Coroutine[object, object, None], *, name: str) -> asyncio.Task[None]:
        """Create and retain one task until it is explicitly discarded or awaited."""
        if self._closed:
            coroutine.close()
            raise RuntimeError(f"task supervisor {self._name!r} is closed")
        if not name:
            coroutine.close()
            raise ValueError("task name must not be empty")
        task = create_owned_task(coroutine, name=name)
        self._tasks.add(task)
        return task

    def discard(self, task: asyncio.Task[None]) -> None:
        """Forget one task after its owner has inspected its result."""
        self._tasks.discard(task)

    async def wait(self) -> None:
        """Await every retained task and retrieve failures as shutdown results."""
        tasks = tuple(self._tasks)
        if not tasks:
            return
        joined = asyncio.gather(*tasks, return_exceptions=True)
        try:
            # The supervisor owns the joined wait. Cancelling one caller must
            # not cancel the children before the owner has released them.
            cancellation_requested = await wait_for_owned(joined)
        finally:
            self._tasks.difference_update(tasks)
        if cancellation_requested:
            raise asyncio.CancelledError

    def close(self) -> None:
        """Reject new tasks while leaving existing work to the owner’s wait policy."""
        self._closed = True


__all__ = ["TaskSupervisor", "create_owned_task", "wait_for_owned"]
