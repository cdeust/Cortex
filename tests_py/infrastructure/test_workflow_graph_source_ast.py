"""Tests for ``workflow_graph_source_ast`` — C3 streaming + bounded waits.

Covers the sharded-popping-harbor C3 contract:
  * ``iter_symbols`` / ``iter_ast_edges`` yield one batch per AP query,
    incrementally — the consumer sees batch N before batch N+1's query is
    issued (fake bridge records fetch order vs. consumer position).
  * A wedged loop / never-completing future raises ``McpConnectionError``
    (bounded cross-loop wait) instead of hanging the worker.
  * No full-set materialization inside the source — peak retained rows
    across the stream is one batch, not the union of all queries.

HARD RULE (prior lesson): never mock ``asyncio.sleep`` for this transport —
a mocked sleep turns the idle loop into a busy-spin hang. These tests use a
real (tiny) sleep and a real bounded wait instead.
"""

from __future__ import annotations

import pytest

from mcp_server.errors import McpConnectionError
from mcp_server.infrastructure import workflow_graph_source_ast as mod
from mcp_server.infrastructure.workflow_graph_source_ast import (
    WorkflowGraphASTSource,
    _SyncLoop,
)


@pytest.fixture(autouse=True)
def _enable_ap(monkeypatch):
    """Force AP enabled + a single graph path; isolate the timeout setting."""
    monkeypatch.setattr(mod, "is_enabled", lambda: True)
    monkeypatch.setattr(mod, "resolve_graph_paths", lambda: ["/fake/graph.kuzu"])
    monkeypatch.setattr(mod, "resolve_graph_path", lambda: "/fake/graph.kuzu")
    from mcp_server.infrastructure import memory_config

    memory_config.get_memory_settings.cache_clear()
    yield
    memory_config.get_memory_settings.cache_clear()


class _RecordingBridge:
    """Fake APBridge that records the ORDER in which queries are issued and
    returns a fixed row list per query. ``calls_at_yield`` lets a test assert
    how many queries had been issued at the moment the consumer pulled item k.

    Each ``query_graph`` returns rows in AP's ``{columns, rows}`` shape so the
    real ``_as_list`` path is exercised. Symbol queries get one synthetic
    symbol per label; edge queries get rows only for the first rel-table so we
    can keep the fixture small while still streaming many (mostly empty) ones.
    """

    def __init__(self, rows_per_query: int = 1) -> None:
        self.query_log: list[str] = []
        self._rows_per_query = rows_per_query

    async def call(self, tool: str, args: dict | None = None):
        assert tool == "query_graph"
        query = (args or {}).get("query", "")
        self.query_log.append(query)
        # Symbol queries: ``MATCH (s:Label) ... RETURN s.qualified_name ...``
        if "qualified_name AS qualified_name" in query or "s.id   AS" in query:
            rows = [
                ["pkg/mod.py::sym%d" % i, "sym%d" % i]
                for i in range(self._rows_per_query)
            ]
            return {"columns": ["qualified_name", "name"], "rows": rows}
        # Edge queries: ``MATCH (src)-[r:Table]->(dst) RETURN src_name, ...``.
        # Only the FIRST edge query returns rows; the rest are empty so the
        # batch count stays small but the stream still issues every query.
        if len(self.query_log) == 1 or "Calls_Function_Function" in query:
            rows = [["a::f", "b::g"] for _ in range(self._rows_per_query)]
            return {"columns": ["src_name", "dst_name"], "rows": rows}
        return {"columns": ["src_name", "dst_name"], "rows": []}

    async def close(self):
        return None


def _make_source(bridge) -> WorkflowGraphASTSource:
    src = WorkflowGraphASTSource(bridge=bridge)
    return src


class TestIncrementalYield:
    def test_symbols_yield_one_batch_per_query_in_order(self):
        """The consumer receives batch 1 strictly before batch 2's query is
        issued — proving per-query streaming, not a single fetch-all."""
        bridge = _RecordingBridge(rows_per_query=2)
        src = _make_source(bridge)
        try:
            seen_query_counts: list[int] = []
            batch_count = 0
            for batch in src.iter_symbols(["/abs/pkg/mod.py"]):
                # At the moment we receive a batch, the number of queries
                # issued so far is recorded. If the source fetched everything
                # up-front, this would equal the TOTAL query count on the very
                # first batch. Incremental streaming → it grows monotonically.
                seen_query_counts.append(len(bridge.query_log))
                batch_count += 1
                if batch_count >= 3:
                    break
            assert batch_count >= 1
            # Strictly increasing: each new batch corresponds to a new query
            # that was issued AFTER the previous batch was consumed.
            assert seen_query_counts == sorted(set(seen_query_counts))
            assert seen_query_counts[0] < len(mod._SYMBOL_LABELS)
        finally:
            src.close()

    def test_edges_yield_incrementally(self):
        bridge = _RecordingBridge(rows_per_query=1)
        src = _make_source(bridge)
        try:
            first_batch_query_count = None
            total = 0
            for _batch in src.iter_ast_edges([]):
                if first_batch_query_count is None:
                    first_batch_query_count = len(bridge.query_log)
                total += 1
            # The first non-empty batch arrived after only a handful of
            # queries — NOT after all ~89 edge queries completed.
            assert first_batch_query_count is not None
            assert first_batch_query_count < 89
        finally:
            src.close()


class TestNoFullMaterialization:
    def test_peak_retained_rows_is_one_batch(self):
        """The source never holds the union of all query results at once.

        We consume the stream but only keep a running max of the CURRENT
        batch size. With N queries each returning R rows, a fetch-all source
        would force a single list of N*R rows somewhere; the generator keeps
        peak retained (per the consumer's own bookkeeping) at R.
        """
        rows = 4
        bridge = _RecordingBridge(rows_per_query=rows)
        src = _make_source(bridge)
        try:
            peak_single_batch = 0
            batches_seen = 0
            for batch in src.iter_symbols(["/abs/pkg/mod.py"]):
                peak_single_batch = max(peak_single_batch, len(batch))
                batches_seen += 1
                # Drop the batch immediately (do NOT accumulate) — emulates a
                # streaming consumer. peak stays at one query's row count.
                del batch
            assert batches_seen >= 1
            assert peak_single_batch == rows
        finally:
            src.close()

    def test_load_symbols_full_set_still_works(self):
        """The list convenience API still returns the full set for genuine
        full-set consumers (builder + len())."""
        bridge = _RecordingBridge(rows_per_query=3)
        src = _make_source(bridge)
        try:
            allrows = src.load_symbols(["/abs/pkg/mod.py"])
            # 21 labels × 3 rows each (every label query returns rows here).
            assert len(allrows) == len(mod._SYMBOL_LABELS) * 3
            assert all("qualified_name" in r for r in allrows)
        finally:
            src.close()


class TestBoundedWaitTimeout:
    def test_run_raises_on_wedged_loop(self, monkeypatch, capfd):
        """A coroutine that never completes must raise McpConnectionError via
        the bounded cross-loop wait — not hang forever. Uses a tiny TEST
        timeout (a test constant, not production) and a REAL sleep (never a
        mocked asyncio.sleep — that would busy-spin the idle loop).

        Regression test for issue #258: closing the loop right after this
        timeout must not race the cancelled task's own finalization — the
        acceptance criterion is literally zero 'Task was destroyed but it
        is pending!' lines on stderr, so this asserts that directly rather
        than only the McpConnectionError."""
        import asyncio
        import gc

        # Tiny timeout for the test only — production default is 3900 s.
        monkeypatch.setenv("CORTEX_MEMORY_AP_SYNC_RESULT_TIMEOUT_S", "0.2")
        from mcp_server.infrastructure import memory_config

        memory_config.get_memory_settings.cache_clear()

        loop_owner = _SyncLoop()
        try:

            async def _never():
                # Real sleep, far longer than the 0.2 s wait ceiling.
                await asyncio.sleep(30)
                return "unreachable"

            with pytest.raises(McpConnectionError):
                loop_owner.run(_never())
        finally:
            loop_owner.close()

        gc.collect()  # force the finalizer of any still-PENDING task now
        assert "Task was destroyed but it is pending" not in capfd.readouterr().err

    def test_run_iter_raises_on_wedged_step(self, monkeypatch, capfd):
        """A streaming step that wedges raises McpConnectionError, and batches
        already yielded before the wedge are real (not silently truncated to a
        full list). Regression test for issue #258 (see docstring above)."""
        import asyncio
        import gc

        monkeypatch.setenv("CORTEX_MEMORY_AP_SYNC_RESULT_TIMEOUT_S", "0.2")
        from mcp_server.infrastructure import memory_config

        memory_config.get_memory_settings.cache_clear()

        loop_owner = _SyncLoop()
        try:

            async def _agen():
                yield [1, 2]
                yield [3, 4]
                await asyncio.sleep(30)  # wedge on the third step
                yield [5, 6]

            got: list = []
            with pytest.raises(McpConnectionError):
                for batch in loop_owner.run_iter(_agen()):
                    got.append(batch)
            # The two pre-wedge batches were really delivered.
            assert got == [[1, 2], [3, 4]]
        finally:
            loop_owner.close()

        gc.collect()
        assert "Task was destroyed but it is pending" not in capfd.readouterr().err


class TestDrainPendingTasks:
    """Direct tests of ``_SyncLoop._drain_pending_tasks`` — the primitive
    ``close()`` relies on to avoid the issue #258 race. Each test pins one
    branch of its contract so a mutation on that branch is caught even
    though the higher-level ``close()``/``run()`` tests above only assert
    the observable absence of the GC warning."""

    def test_drain_cancels_and_awaits_a_genuinely_wedged_task(self):
        """postcondition: after ``_drain_pending_tasks()`` returns, a task
        that was mid-``asyncio.sleep(30)`` on the pinned loop has reached a
        terminal (cancelled) state — not left ``PENDING`` — and the call
        itself returns almost immediately (well under the shutdown-drain
        ceiling), proving it does not busy-wait for the full timeout."""
        import asyncio
        import time

        loop_owner = _SyncLoop()
        try:
            loop = loop_owner._ensure_loop()

            async def _never():
                await asyncio.sleep(30)

            task_future = asyncio.run_coroutine_threadsafe(_never(), loop)
            time.sleep(0.05)  # let the task actually start on the loop thread

            t0 = time.monotonic()
            loop_owner._drain_pending_tasks()
            elapsed = time.monotonic() - t0

            assert task_future.done()
            assert task_future.cancelled()
            # Cancelling a sleep() completes in well under a second; bound
            # generously below the 2 s shutdown-drain ceiling so a mutant
            # that skips cancellation (and forces the full timeout) fails.
            assert elapsed < 1.0
        finally:
            loop_owner.close()

    def test_drain_is_a_noop_when_loop_was_never_initialized(self):
        """precondition guard: ``self._loop is None`` (a ``_SyncLoop`` that
        never ran anything) must return immediately without error."""
        owner = _SyncLoop()
        owner._drain_pending_tasks()  # must not raise
        assert owner._loop is None

    def test_drain_is_a_noop_for_a_non_asyncio_loop(self):
        """Guard: a test double standing in for ``self._loop`` (not a real
        ``asyncio.AbstractEventLoop``) is never scheduled against — doing so
        would leave the drain coroutine permanently unawaited (a real
        regression this test caught: see ``_drain_pending_tasks``'s
        docstring). Returns near-instantly rather than timing out."""
        import time
        from unittest.mock import MagicMock

        owner = _SyncLoop.__new__(_SyncLoop)
        loop = MagicMock()
        loop.is_closed.return_value = False
        owner._loop = loop
        owner._thread = MagicMock()

        t0 = time.monotonic()
        owner._drain_pending_tasks()  # must not raise, must not schedule
        assert time.monotonic() - t0 < 0.5

    def test_drain_is_a_noop_when_the_loop_thread_already_exited(self):
        """Guard: the pinned loop is real and not yet closed, but its
        ``run_forever()`` thread has already returned — nothing can drive a
        scheduled drain coroutine, so skip rather than block for the full
        shutdown-drain ceiling waiting on a callback that will never run."""
        import time

        loop_owner = _SyncLoop()
        try:
            loop = loop_owner._ensure_loop()
            loop.call_soon_threadsafe(loop.stop)
            loop_owner._thread.join(timeout=2.0)
            assert not loop_owner._thread.is_alive()
            assert not loop.is_closed()

            t0 = time.monotonic()
            loop_owner._drain_pending_tasks()
            assert time.monotonic() - t0 < 0.5
        finally:
            loop.close()
            loop_owner._loop = None
            loop_owner._thread = None

    def test_drain_times_out_and_logs_when_a_task_is_slow_to_cancel(
        self, monkeypatch, caplog
    ):
        """postcondition (timeout branch): a task that takes LONGER than
        the shutdown-drain ceiling to actually honor its cancellation must
        not block ``_drain_pending_tasks()`` past that ceiling — it logs
        the actionable, correctly-worded message and returns. Pins both
        the bound (``_SHUTDOWN_DRAIN_TIMEOUT_S``, not an unbounded wait)
        and the message content, since a garbled/blank log line here is
        the only signal an operator gets for a genuinely wedged task."""
        import asyncio
        import time

        # Tiny ceiling for the test only — shrinks the real 2.0s constant.
        monkeypatch.setattr(mod, "_SHUTDOWN_DRAIN_TIMEOUT_S", 0.05)

        loop_owner = _SyncLoop()
        try:
            loop = loop_owner._ensure_loop()

            async def _slow_to_cancel():
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    # Simulates real (slower-than-the-ceiling) cleanup —
                    # still honors cancellation, just not within 0.05s.
                    await asyncio.sleep(0.3)
                    raise

            asyncio.run_coroutine_threadsafe(_slow_to_cancel(), loop)
            time.sleep(0.05)  # let the task actually start

            with caplog.at_level(
                "DEBUG", logger="mcp_server.infrastructure.workflow_graph_source_ast"
            ):
                t0 = time.monotonic()
                loop_owner._drain_pending_tasks()
                elapsed = time.monotonic() - t0

            # Returned at the (monkeypatched) ceiling, not after the
            # task's slower real cancellation ~0.3s later.
            assert elapsed < 0.2
            # Exact match (not a substring check): the log line is the
            # only signal an operator gets for a genuinely wedged task,
            # so both the wording AND the interpolated ceiling value must
            # be correct — a substring check alone can't distinguish
            # "wrapped/garbled text that still contains the phrase" or
            # "the %.1fs placeholder left un-interpolated" from the real
            # message.
            expected = (
                f"AP sync-loop drain exceeded {mod._SHUTDOWN_DRAIN_TIMEOUT_S:.1f}s "
                "— leaving residual task(s) for interpreter-exit cleanup"
            )
            assert any(r.getMessage() == expected for r in caplog.records)

            # Let the task actually finish before teardown so close()'s
            # own drain call (same monkeypatched ceiling) finds nothing
            # pending — otherwise the loop would be closed on top of a
            # still-running task, which is exactly the #258 shape this
            # test is not meant to also exercise.
            time.sleep(0.4)
        finally:
            loop_owner.close()


class TestSyncLoopCloseRealLoop:
    """``close()`` tests against a genuine pinned loop (as opposed to the
    ``MagicMock``-based error-swallowing tests in
    ``test_s110_sweep_infrastructure.py``): these pin the actual
    stop/join/close sequence's observable effect."""

    def test_close_on_never_initialized_loop_is_a_noop(self):
        """Guard: a fresh ``_SyncLoop`` that never ran anything has
        ``self._loop is None`` — ``close()`` must short-circuit before
        touching ``self._loop.is_closed()`` (which would raise
        ``AttributeError`` on ``None``), not attempt it."""
        owner = _SyncLoop()
        owner.close()  # must not raise
        assert owner._loop is None
        assert owner._thread is None

    def test_close_on_real_loop_actually_stops_and_closes_it(self):
        """postcondition: ``close()`` on a genuinely running pinned loop
        leaves the loop closed and both instance attributes reset to
        ``None`` (not merely falsy) — the observable proof that
        ``loop.stop()`` was actually invoked (not just scheduled and
        ignored) and the loop's thread actually exited before
        ``loop.close()`` ran."""
        loop_owner = _SyncLoop()
        loop = loop_owner._ensure_loop()

        loop_owner.close()

        assert loop.is_closed()
        assert loop_owner._loop is None
        assert loop_owner._thread is None


class TestSingleReaderOwnership:
    def test_one_loop_thread_owns_the_loop(self):
        """Document + verify single-reader ownership: one ap-sync-loop thread
        services every call (Lamport H4 — one reader over one pipe)."""
        import threading

        loop_owner = _SyncLoop()
        try:
            seen_threads: set[int] = set()

            async def _who():
                seen_threads.add(threading.get_ident())
                return threading.get_ident()

            t1 = loop_owner.run(_who())
            t2 = loop_owner.run(_who())
            # Both coroutines ran on the SAME (single) loop thread.
            assert t1 == t2
            assert len(seen_threads) == 1
            # And it is NOT the caller's thread.
            assert t1 != threading.get_ident()
        finally:
            loop_owner.close()


class TestDisabledDegradation:
    def test_iter_symbols_empty_when_disabled(self, monkeypatch):
        monkeypatch.setattr(mod, "is_enabled", lambda: False)
        src = _make_source(_RecordingBridge())
        try:
            assert list(src.iter_symbols(["/x.py"])) == []
            assert src.load_symbols(["/x.py"]) == []
        finally:
            src.close()
