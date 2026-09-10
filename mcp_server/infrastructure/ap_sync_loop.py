"""Infrastructure layer only. No core imports.

source: ADR-0502"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Iterator

from mcp_server.errors import McpConnectionError

logger = logging.getLogger(__name__)

# source: ADR-0502
_AP_SYNC_PROBE_INTERVAL_S = 30.0


# source: ADR-0502
_SHUTDOWN_DRAIN_TIMEOUT_S = 2.0


class _SyncLoop:
    """Owns a single event loop + runs coroutines on it synchronously.

        The MCP client spawns the AP subprocess and binds its stdin/stdout
        to the *current* event loop. If we close that loop between calls,
        subsequent writes to those streams raise ``RuntimeError: Event loop
        is closed``. This helper pins one loop for the lifetime of a caller
        so every AP call shares the same loop/transport.

    source: ADR-0502"""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            loop = self._loop  # non-Optional local captured by the loop thread

            def _run_forever():
                # source: ADR-0502
                asyncio.set_event_loop(loop)
                loop.run_forever()

            self._thread = threading.Thread(
                target=_run_forever,
                name="ap-sync-loop",
                daemon=True,
            )
            self._thread.start()
        return self._loop

    def run(self, coro):
        """Run ``coro`` on the pinned loop and block until it completes.

        source: ADR-0502"""
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return self._result_or_wedged(future, "call")

    def run_iter(self, agen) -> Iterator[Any]:
        """Drive an async generator one step per bounded cross-loop call,
                yielding each item synchronously to the caller.

        source: ADR-0502"""
        loop = self._ensure_loop()
        _sentinel = object()

        async def _step():
            try:
                return await agen.__anext__()
            except StopAsyncIteration:
                return _sentinel

        while True:
            future = asyncio.run_coroutine_threadsafe(_step(), loop)
            item = self._result_or_wedged(future, "step")
            if item is _sentinel:
                return
            yield item

    def _result_or_wedged(self, future, what: str):
        """Block until ``future`` resolves — no wall-clock ceiling.

        source: ADR-0502"""
        while True:
            try:
                return future.result(timeout=_AP_SYNC_PROBE_INTERVAL_S)
            except FutureTimeoutError:
                if _loop_is_drainable(self._loop, self._thread):
                    continue  # loop thread still alive — keep waiting
                future.cancel()
                raise McpConnectionError(
                    f"AP reader-thread {what} abandoned: the pinned loop thread "
                    "is no longer running, so the call can never complete"
                ) from None

    def close(self) -> None:
        if self._loop and not self._loop.is_closed():
            self._drain_pending_tasks()
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except RuntimeError:
                # Loop already closed between the check and the call.
                pass
            try:
                if self._thread is not None:
                    self._thread.join(timeout=_SHUTDOWN_DRAIN_TIMEOUT_S)
            except RuntimeError:
                # Joining the current thread — nothing to wait for.
                pass
            try:
                self._loop.close()
            except RuntimeError:
                # Loop still running (stop not yet processed); leaked loop
                # is reclaimed at interpreter exit.
                pass
        self._loop = None
        self._thread = None

    def _drain_pending_tasks(self) -> None:
        """Cancel + await every task still running on the pinned loop.

                precondition: none — safe to call on any ``_SyncLoop`` state.
                postcondition: every task ``asyncio.all_tasks(loop)`` reported
                (other than the drain task itself) has reached a terminal state
                when this returns, UNLESS ``_SHUTDOWN_DRAIN_TIMEOUT_S`` elapsed
                first (residual task logged, left for interpreter-exit GC).

        source: ADR-0502"""
        loop = self._loop
        if loop is None or not _loop_is_drainable(loop, self._thread):
            return
        _run_task_drain(loop)


def _loop_is_drainable(
    loop: "asyncio.AbstractEventLoop | None", thread: "threading.Thread | None"
) -> bool:
    """Guard: only a genuine, live, running loop can host a scheduled drain.

    source: ADR-0502"""
    if loop is None or loop.is_closed():
        return False
    if not isinstance(loop, asyncio.AbstractEventLoop):
        return False
    if thread is None or not thread.is_alive():
        return False
    return True


async def _cancel_and_await_pending(loop: "asyncio.AbstractEventLoop") -> None:
    """Equivalent-mutant note (mutmut _drain_pending_tasks__mutmut_9,
        __mutmut_11): passing ``loop`` explicitly vs. omitting it (defaulting
        to ``get_running_loop()``) is unobservable — this coroutine is only
        ever scheduled via ``run_coroutine_threadsafe(this(loop), loop)``, so
        ``get_running_loop()`` IS ``loop`` on every call. Kept explicit for
        readability, not behavior.

    source: ADR-0502"""
    current = asyncio.current_task(loop)
    pending = [t for t in asyncio.all_tasks(loop) if t is not current and not t.done()]
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def _run_task_drain(loop: "asyncio.AbstractEventLoop") -> None:
    """Schedule ``_cancel_and_await_pending`` on ``loop`` and block the
        calling thread until it finishes or times out.

    source: ADR-0502"""
    try:
        future = asyncio.run_coroutine_threadsafe(_cancel_and_await_pending(loop), loop)
    except RuntimeError:
        return  # loop thread already exited on its own; nothing to drain
    try:
        future.result(timeout=_SHUTDOWN_DRAIN_TIMEOUT_S)
    except FutureTimeoutError:
        logger.debug(
            "AP sync-loop drain exceeded %.1fs — leaving residual "
            "task(s) for interpreter-exit cleanup",
            _SHUTDOWN_DRAIN_TIMEOUT_S,
        )
    except RuntimeError:
        pass  # loop closed between the check above and this call


__all__ = ["_SyncLoop", "_AP_SYNC_PROBE_INTERVAL_S", "_SHUTDOWN_DRAIN_TIMEOUT_S"]
