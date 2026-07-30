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
            raise McpConnectionError(
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
        _SENTINEL = object()

        async def _step():
            try:
                return await agen.__anext__()
            except StopAsyncIteration:
                return _SENTINEL

        while True:
            future = asyncio.run_coroutine_threadsafe(_step(), loop)
            try:
                item = future.result(timeout=_ap_sync_timeout_s())
            except FutureTimeoutError as exc:
                future.cancel()
                raise McpConnectionError(
                    "AP reader-thread step exceeded "
                    f"{_ap_sync_timeout_s():.0f}s — subprocess presumed wedged"
                ) from exc
            if item is _SENTINEL:
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

        precondition: ``self._loop`` is not ``None`` and not yet closed.
        postcondition: every task ``asyncio.all_tasks(loop)`` reported
        (other than this method's own drain task) has reached a terminal
        state (done or cancelled) when this call returns — UNLESS
        ``_SHUTDOWN_DRAIN_TIMEOUT_S`` elapsed first, in which case the
        residual task is logged and left for interpreter-exit GC rather
        than blocking teardown indefinitely.

        Without this step, ``close()`` would schedule ``loop.stop()``
        immediately after a ``run``/``run_iter`` timeout's
        ``future.cancel()``. ``loop.stop()`` only lets the CURRENT batch
        of ready callbacks finish; it does not run callbacks THAT batch
        goes on to schedule. ``future.cancel()`` merely *schedules* the
        underlying task's ``Task.cancel()`` — actually delivering the
        ``CancelledError`` into the coroutine takes one further loop
        iteration. If ``run_forever()`` returns before that iteration
        runs, the task is left ``PENDING`` and, once this object (or the
        interpreter) later garbage-collects it, asyncio logs "Task was
        destroyed but it is pending!" (issue #258 — reproduced and
        confirmed via instrumented probe before this fix).

        happens-before: the drain coroutine below runs ON the pinned loop
        and directly ``await``s ``asyncio.gather`` over every pending
        task, so it observes the loop run however many iterations a
        cancellation needs to complete — not just the ones already
        processed by the time this method is called. ``future.result()``
        blocks the CALLING thread until that gather finishes (or the
        timeout fires), so ``close()``'s subsequent ``loop.stop()`` is
        strictly ordered after every drained task's terminal transition.

        Guarded to a genuine, live pinned loop (real ``AbstractEventLoop``
        + a thread confirmed alive): scheduling a coroutine via
        ``run_coroutine_threadsafe`` onto anything else (a test double
        standing in for the loop, or a loop whose ``run_forever()``
        thread already exited without closing it) never actually drives
        the coroutine — the scheduled callback that would consume it sits
        queued forever, and ``loop.close()`` a few lines below drops that
        queue (``self._ready.clear()``), which is Python's OWN trigger for
        "coroutine was never awaited". Skipping the drain in that case
        leaves ``close()`` exactly as safe as it was before this method
        existed for those callers (``_SyncLoop.__new__`` + a mocked
        ``_loop``/``_thread`` is an established test pattern for
        exercising this method's error-swallowing branches in isolation —
        see ``test_sync_loop_join_runtimeerror_is_swallowed``).
        """
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        if not isinstance(loop, asyncio.AbstractEventLoop):
            return  # test double standing in for the loop — nothing to drain
        if self._thread is None or not self._thread.is_alive():
            return  # loop's thread already exited — no runner to drive the drain

        async def _drain() -> None:
            # Equivalent-mutant note (mutmut _drain_pending_tasks__mutmut_9,
            # __mutmut_11): passing ``loop`` explicitly here vs. omitting it
            # (defaulting to ``get_running_loop()``) is not observable —
            # ``_drain`` is only ever scheduled via
            # ``run_coroutine_threadsafe(_drain(), loop)`` a few lines below,
            # so ``get_running_loop()`` inside this body IS ``loop`` on every
            # call, always. Kept explicit for readability (this function
            # reasons about a specific, named loop), not for behavior.
            current = asyncio.current_task(loop)
            pending = [
                t for t in asyncio.all_tasks(loop) if t is not current and not t.done()
            ]
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        try:
            future = asyncio.run_coroutine_threadsafe(_drain(), loop)
        except RuntimeError:
            # Loop thread already exited on its own; nothing to drain.
            return
        try:
            future.result(timeout=_SHUTDOWN_DRAIN_TIMEOUT_S)
        except FutureTimeoutError:
            logger.debug(
                "AP sync-loop drain exceeded %.1fs — leaving residual "
                "task(s) for interpreter-exit cleanup",
                _SHUTDOWN_DRAIN_TIMEOUT_S,
            )
        except RuntimeError:
            # Loop closed between the check above and this call.
            pass


__all__ = ["_SyncLoop", "_ap_sync_timeout_s", "_SHUTDOWN_DRAIN_TIMEOUT_S"]
