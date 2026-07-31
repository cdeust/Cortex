"""Cross-loop sync/drain primitive backing the AST-source AP bridge.

Split out of ``workflow_graph_source_ast.py`` (issue #275 — that file
exceeded the 300-line cap) as its own cohesive concern: pinning one
event loop across a caller's lifetime and exposing a bounded, synchronous
façade over it. ``workflow_graph_source_ast.py`` re-exports ``_SyncLoop``
so existing import paths (``from
mcp_server.infrastructure.workflow_graph_source_ast import _SyncLoop``)
keep working.

Infrastructure layer only. No core imports.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Iterator

from mcp_server.errors import McpConnectionError
from mcp_server.infrastructure.memory_config import get_memory_settings

logger = logging.getLogger(__name__)


def _ap_sync_timeout_s() -> float:
    """Cross-loop wait ceiling for AP reader-thread calls.

    source: memory_config.AP_SYNC_RESULT_TIMEOUT_S (see that field's
    derivation comment — floored at the in-loop 3600 s AP-call ceiling
    plus a drain margin). Read lazily so env overrides apply per-process.
    """

    return float(get_memory_settings().AP_SYNC_RESULT_TIMEOUT_S)


# Shutdown-drain ceiling for ``_SyncLoop.close()``: bounds how long we wait
# for tasks still running on the pinned loop to reach a terminal state
# after being cancelled, before stopping the loop and joining its thread.
# source: measured 2026-07-30 (macOS, CPython 3.12.12) — a cancelled
#   ``asyncio.sleep(30)`` task (the wedge shape ``run``/``run_iter`` produce
#   on a cross-loop timeout, issue #258) completes its cancellation in
#   <1ms once ``asyncio.gather`` is awaited on the owning loop; three
#   repeated trials all finished within 1ms. 2.0s reuses the grace period
#   this method already applied to ``self._thread.join(...)`` below,
#   giving headroom for a genuine (non-test) wedge where the abandoned
#   coroutine's own cleanup does real I/O before honoring cancellation.
_SHUTDOWN_DRAIN_TIMEOUT_S = 2.0


class _SyncLoop:
    """Owns a single event loop + runs coroutines on it synchronously.

    The MCP client spawns the AP subprocess and binds its stdin/stdout
    to the *current* event loop. If we close that loop between calls,
    subsequent writes to those streams raise ``RuntimeError: Event loop
    is closed``. This helper pins one loop for the lifetime of a caller
    so every AP call shares the same loop/transport.

    When called from *inside* a running event loop (e.g. a FastMCP
    async handler), we run the coroutine on the private loop inside a
    dedicated thread so we never compete with the outer loop. That is
    the only reliable way to expose a sync façade to async callers
    without leaking thread-local state.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            loop = self._loop  # non-Optional local captured by the loop thread

            def _run_forever():
                # Equivalent-mutant note (mutmut _ensure_loop__mutmut_5:
                # ``set_event_loop(None)``): thread-local registration is
                # unobservable here — every coroutine/callback this thread
                # ever runs executes strictly inside ``loop.run_forever()``,
                # so ``asyncio.get_event_loop()``/``get_running_loop()``
                # already resolve to this exact loop via CPython's
                # `_set_running_loop` bookkeeping (set for the duration of
                # `run_forever()`), independent of this call. Verified: the
                # full `tests_py/infrastructure/` suite (710 tests) is
                # unaffected by removing this line. Kept anyway as the
                # standard defensive idiom for "run a loop on a dedicated
                # thread" (asyncio docs), in case a future AP-bridge
                # dependency calls the legacy no-arg accessor outside a
                # running-loop context.
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

        Single-reader-thread ownership (verified): ``_ensure_loop`` spawns
        exactly one ``ap-sync-loop`` thread that owns the loop for this
        ``_SyncLoop``'s lifetime; every AP call funnels through here onto
        that one loop. No other thread drives the loop, so the JSON-RPC
        pipe has a single reader (Lamport H4 satisfied by construction).

        The wait is bounded: if the loop thread wedges (e.g. the AP
        subprocess stalls below the in-loop await), ``.result(timeout=…)``
        raises rather than hanging this worker forever. On timeout we never
        return partial data — we raise ``McpConnectionError``.
        """
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout=_ap_sync_timeout_s())
        except FutureTimeoutError as exc:
            future.cancel()
            raise McpConnectionError(  # noqa: TRY003 — one-off message, not reused (§3.3)
                "AP reader-thread call exceeded "
                f"{_ap_sync_timeout_s():.0f}s — subprocess presumed wedged"
            ) from exc

    def run_iter(self, agen) -> Iterator[Any]:
        """Drive an async generator one step per bounded cross-loop call,
        yielding each item synchronously to the caller.

        This is the streaming primitive: ``agen`` (an async generator that
        yields one batch per AP query) is advanced one ``__anext__`` at a
        time, each on the pinned loop with a bounded ``.result(timeout=…)``.
        The caller therefore receives batch *N* (and may process/discard it)
        BEFORE batch *N+1*'s query is ever issued — peak retained inside the
        source is one batch, not the union across all queries.

        On a wedged loop thread, each step raises ``McpConnectionError``
        rather than hanging. Partial batches already yielded are real data;
        the generator stops at the failed step (it does not silently return
        a truncated full list).
        """
        loop = self._ensure_loop()
        _sentinel = object()

        async def _step():
            try:
                return await agen.__anext__()
            except StopAsyncIteration:
                return _sentinel

        while True:
            future = asyncio.run_coroutine_threadsafe(_step(), loop)
            try:
                item = future.result(timeout=_ap_sync_timeout_s())
            except FutureTimeoutError as exc:
                future.cancel()
                raise McpConnectionError(  # noqa: TRY003 — one-off message, not reused (§3.3)
                    "AP reader-thread step exceeded "
                    f"{_ap_sync_timeout_s():.0f}s — subprocess presumed wedged"
                ) from exc
            if item is _sentinel:
                return
            yield item

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

        Without this step, ``close()`` would call ``loop.stop()``
        immediately after a ``run``/``run_iter`` timeout's
        ``future.cancel()`` — which only *schedules* cancellation;
        delivering it takes one more loop iteration ``run_forever()``
        may never reach, leaving the task ``PENDING`` and, once GC'd,
        logging "Task was destroyed but it is pending!" (issue #258,
        reproduced via instrumented probe before this fix). See
        ``_loop_is_drainable`` for the live-loop guard and
        ``_run_task_drain`` for the schedule/await/timeout contract
        (including the happens-before argument for why ``close()``'s
        subsequent ``loop.stop()`` is safe).
        """
        loop = self._loop
        if loop is None or not _loop_is_drainable(loop, self._thread):
            return
        _run_task_drain(loop)


def _loop_is_drainable(
    loop: "asyncio.AbstractEventLoop | None", thread: "threading.Thread | None"
) -> bool:
    """Guard: only a genuine, live, running loop can host a scheduled drain.

    Refuses a ``None``/closed loop (nothing to drain); a test double
    standing in for the loop (not a real ``AbstractEventLoop`` — scheduling
    against it would leave the drain coroutine queued forever, since
    nothing ever runs it, which is Python's own trigger for "coroutine
    was never awaited"); and a loop whose ``run_forever()`` thread already
    exited (no runner left to drive the scheduled callback). Guarding this
    way leaves the caller exactly as safe as it was before this drain step
    existed for those cases (``_SyncLoop.__new__`` + a mocked
    ``_loop``/``_thread`` is an established test pattern for exercising
    the surrounding error-swallowing branches in isolation — see
    ``test_sync_loop_join_runtimeerror_is_swallowed``).
    """
    if loop is None or loop.is_closed():
        return False
    if not isinstance(loop, asyncio.AbstractEventLoop):
        return False
    if thread is None or not thread.is_alive():
        return False
    return True


async def _cancel_and_await_pending(loop: "asyncio.AbstractEventLoop") -> None:
    """Cancel + await every non-current task on ``loop``. Runs ON ``loop``
    (scheduled via ``run_coroutine_threadsafe`` — never called directly).

    Equivalent-mutant note (mutmut _drain_pending_tasks__mutmut_9,
    __mutmut_11): passing ``loop`` explicitly vs. omitting it (defaulting
    to ``get_running_loop()``) is unobservable — this coroutine is only
    ever scheduled via ``run_coroutine_threadsafe(this(loop), loop)``, so
    ``get_running_loop()`` IS ``loop`` on every call. Kept explicit for
    readability, not behavior.
    """
    current = asyncio.current_task(loop)
    pending = [t for t in asyncio.all_tasks(loop) if t is not current and not t.done()]
    for t in pending:
        t.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def _run_task_drain(loop: "asyncio.AbstractEventLoop") -> None:
    """Schedule ``_cancel_and_await_pending`` on ``loop`` and block the
    calling thread until it finishes or times out.

    happens-before: the scheduled coroutine runs ON ``loop`` and directly
    ``await``s ``asyncio.gather`` over every pending task, so it observes
    the loop run however many iterations a cancellation needs — not just
    the ones already processed by the time this is called.
    ``future.result()`` blocks the calling thread until that gather
    finishes (or the timeout fires), so the caller's subsequent
    ``loop.stop()`` is strictly ordered after every drained task's
    terminal transition.
    """
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


__all__ = ["_SyncLoop", "_ap_sync_timeout_s", "_SHUTDOWN_DRAIN_TIMEOUT_S"]
