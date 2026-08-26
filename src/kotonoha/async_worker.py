"""Explicit ownership for bounded blocking calls used by async services."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial
from typing import ParamSpec, TypeVar

_P = ParamSpec("_P")
_R = TypeVar("_R")
DEFAULT_BLOCKING_CALL_TIMEOUT_S = 30.0


class BlockingCallRunner:
    """Run blocking calls in one explicitly owned worker.

    The executor is created lazily and is never process-global. A cancelled or
    timed-out awaitable is shielded from the underlying concurrent future: the
    caller stops waiting, but the blocking operation is allowed to finish. The
    owner must call :meth:`close`; closing cancels queued work and lets an already
    running call finish without blocking the event loop.
    """

    def __init__(self, thread_name_prefix: str) -> None:
        if not thread_name_prefix:
            raise ValueError("blocking worker name must not be empty")
        self._thread_name_prefix = thread_name_prefix
        self._executor: ThreadPoolExecutor | None = None
        self._closed = False

    async def run(self, function: Callable[_P, _R], /, *args: _P.args, **kwargs: _P.kwargs) -> _R:
        """Run one call with the default deadline and cancellation semantics."""
        return await self._run(DEFAULT_BLOCKING_CALL_TIMEOUT_S, function, *args, **kwargs)

    async def run_with_timeout(
        self,
        timeout: float,
        function: Callable[_P, _R],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _R:
        """Run one call with an explicit positive deadline."""
        return await self._run(timeout, function, *args, **kwargs)

    async def _run(
        self,
        timeout: float,
        function: Callable[_P, _R],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _R:
        """Submit a call and keep its thread future owned after cancellation."""
        if self._closed:
            raise RuntimeError("blocking call runner is closed")
        if isinstance(timeout, bool) or timeout <= 0.0:
            raise ValueError("blocking call timeout must be positive")
        executor = self._executor
        if executor is None:
            executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=self._thread_name_prefix)
            self._executor = executor
        future: Future[_R] = executor.submit(partial(function, *args, **kwargs))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            # Cooperative polling is intentional. On the supported Python 3.14
            # runtime, asyncio.wrap_future can fail to deliver futures whose
            # worker result crosses SQLite's C boundary. Polling keeps the loop
            # responsive without transferring that result through asyncio's
            # concurrent-future bridge.
            while not future.done():
                remaining = deadline - loop.time()
                if remaining <= 0.0:
                    future.cancel()  # cancels only queued work; running calls finish
                    raise TimeoutError("blocking call exceeded its deadline")
                await asyncio.sleep(min(0.01, remaining))
            return future.result()
        except asyncio.CancelledError:
            # Do not call future.cancel(): a caller cancelling this awaitable must
            # not be mistaken for cancelling an already-running filesystem,
            # SQLite, or keyring operation.
            raise

    def close(self) -> None:
        """Release queued work and detach the owned executor without blocking."""
        if self._closed:
            return
        self._closed = True
        executor = self._executor
        self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["BlockingCallRunner", "DEFAULT_BLOCKING_CALL_TIMEOUT_S"]
