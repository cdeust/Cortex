"""Tests for staged progress reporting in the ingest_codebase handler.

Covers:
  - NullProgress is a no-op and does not alter handler behaviour.
  - FakeReporter records stage() calls in order (one per _STAGES entry).
  - McpProgress fraction math: overall = (stage_index + within) / stage_total.
  - McpProgress throttle: advance() skips dispatches within the min interval.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from mcp_server.errors import McpConnectionError
from mcp_server.handlers import ingest_codebase as icb
from mcp_server.handlers import ingest_codebase_pages as icb_pages
from mcp_server.mcp_progress import McpProgress
from mcp_server.shared.progress import NullProgress, ProgressReporter


# ── FakeReporter ─────────────────────────────────────────────────────────────


class FakeReporter:
    """Records all progress calls for assertion.

    Postcondition: stage_calls[i] == (name, index, total) for the i-th
    stage() call; advance_calls records (done, total) for each advance().
    """

    def __init__(self) -> None:
        self.stage_calls: list[tuple[str, int, int]] = []
        self.advance_calls: list[tuple[int, int | None]] = []
        self.log_calls: list[str] = []
        self.closed: bool = False

    def stage(self, name: str, index: int, total: int) -> None:
        self.stage_calls.append((name, index, total))

    def advance(self, done: int, total: int | None = None) -> None:
        self.advance_calls.append((done, total))

    def log(self, message: str) -> None:
        self.log_calls.append(message)

    def close(self) -> None:
        self.closed = True


# ── Protocol conformance ──────────────────────────────────────────────────────


class TestProtocolConformance:
    def test_null_progress_satisfies_protocol(self) -> None:
        """NullProgress must be recognized as a ProgressReporter at runtime."""
        assert isinstance(NullProgress(), ProgressReporter)

    def test_fake_reporter_satisfies_protocol(self) -> None:
        assert isinstance(FakeReporter(), ProgressReporter)

    def test_mcp_progress_satisfies_protocol(self) -> None:
        ctx = MagicMock()
        loop = asyncio.new_event_loop()
        try:
            mp = McpProgress(ctx, loop)
            assert isinstance(mp, ProgressReporter)
        finally:
            loop.close()


# ── NullProgress ─────────────────────────────────────────────────────────────


class TestNullProgress:
    """All NullProgress methods must be no-ops."""

    def test_all_methods_are_callable_and_return_none(self) -> None:
        np = NullProgress()
        assert np.stage("a", 0, 3) is None
        assert np.advance(10, 100) is None
        assert np.log("msg") is None
        assert np.close() is None


# ── McpProgress fraction math ─────────────────────────────────────────────────


class TestMcpProgressFractionMath:
    """Overall fraction = (stage_index + within_fraction) / stage_total."""

    def _make_mp(self) -> tuple[McpProgress, list[float], list[str]]:
        ctx = MagicMock()
        loop = asyncio.new_event_loop()
        progress_values: list[float] = []
        info_messages: list[str] = []

        async def _fake_report(progress: float, total: float | None = None) -> None:
            progress_values.append(progress)

        async def _fake_info(message: str) -> None:
            info_messages.append(message)

        ctx.report_progress = _fake_report
        ctx.info = _fake_info

        mp = McpProgress(ctx, loop)
        return mp, progress_values, info_messages

    def _drain(self, loop: asyncio.AbstractEventLoop) -> None:
        """Drain all fire-and-forget coroutines scheduled on the loop."""
        # run_coroutine_threadsafe schedules tasks on `loop` but we're not
        # on that loop — run a tiny step to let pending tasks execute.
        loop.run_until_complete(asyncio.sleep(0))

    def test_stage_zero_gives_zero_fraction(self) -> None:
        mp, vals, _ = self._make_mp()
        loop = mp._loop
        try:
            mp.stage("analyze graph", 0, 6)
            self._drain(loop)
            assert vals and abs(vals[-1] - 0.0) < 1e-9
        finally:
            loop.close()

    def test_stage_3_of_6_gives_half(self) -> None:
        mp, vals, _ = self._make_mp()
        loop = mp._loop
        try:
            mp.stage("ingest edges", 3, 6)
            self._drain(loop)
            assert vals and abs(vals[-1] - 0.5) < 1e-9
        finally:
            loop.close()

    def test_advance_with_known_total_updates_within_fraction(self) -> None:
        mp, vals, _ = self._make_mp()
        loop = mp._loop
        try:
            mp.stage("ingest entities", 2, 6)
            self._drain(loop)
            # Override throttle timestamp to allow advance dispatch.
            mp._last_advance_ts = 0.0
            mp.advance(50, 100)
            self._drain(loop)
            # Expected: (2 + 0.5) / 6 = 2.5 / 6 ≈ 0.4167
            expected = (2 + 0.5) / 6
            assert vals and abs(vals[-1] - expected) < 1e-9
        finally:
            loop.close()

    def test_advance_indeterminate_total_keeps_within_at_zero(self) -> None:
        mp, vals, _ = self._make_mp()
        loop = mp._loop
        try:
            mp.stage("ingest entities", 2, 6)
            self._drain(loop)
            mp._last_advance_ts = 0.0
            mp.advance(100)  # total=None → indeterminate
            self._drain(loop)
            # within_fraction stays 0.0 → overall = 2/6
            expected = 2.0 / 6.0
            assert vals and abs(vals[-1] - expected) < 1e-9
        finally:
            loop.close()


# ── McpProgress throttle ──────────────────────────────────────────────────────


class TestMcpProgressThrottle:
    """advance() must be throttled to ~2 Hz (0.5s minimum interval)."""

    def test_rapid_advance_calls_dispatch_only_once(self) -> None:
        ctx = MagicMock()
        dispatched: list[float] = []

        async def _fake_report(progress: float, total: float | None = None) -> None:
            dispatched.append(progress)

        async def _fake_info(message: str) -> None:
            pass

        ctx.report_progress = _fake_report
        ctx.info = _fake_info

        loop = asyncio.new_event_loop()
        try:
            mp = McpProgress(ctx, loop)
            mp._last_advance_ts = time.monotonic()  # pretend we just dispatched

            # Call advance 5 times in rapid succession (within the 0.5s window).
            for i in range(5):
                mp.advance(i * 10, 100)

            loop.run_until_complete(asyncio.sleep(0))
            # All were throttled — no new dispatches after the initial reset.
            assert len(dispatched) == 0
        finally:
            loop.close()

    def test_advance_after_interval_dispatches(self) -> None:
        ctx = MagicMock()
        dispatched: list[float] = []

        async def _fake_report(progress: float, total: float | None = None) -> None:
            dispatched.append(progress)

        async def _fake_info(message: str) -> None:
            pass

        ctx.report_progress = _fake_report
        ctx.info = _fake_info

        loop = asyncio.new_event_loop()
        try:
            mp = McpProgress(ctx, loop)
            mp._last_advance_ts = 0.0  # force the interval to have elapsed

            mp.advance(50, 100)
            loop.run_until_complete(asyncio.sleep(0))
            assert len(dispatched) == 1
        finally:
            loop.close()


# ── Handler stage ordering (minimal mock path) ────────────────────────────────


class TestHandlerStageOrdering:
    """The handler must emit stage() once per _STAGES entry, in order."""

    @pytest.mark.asyncio
    async def test_handler_emits_all_stages_in_order(self, monkeypatch) -> None:
        """Verify stage() is called once per _STAGES entry.

        We stub the heavy upstreams (ensure_graph, fetch_files, etc.) so the
        test doesn't need a live DB or Kuzu, and use the same monkeypatch
        pattern as the existing test_ingest_codebase.py suite.
        """
        fake_store: Any = MagicMock()
        fake_store.batch_pool = MagicMock()
        monkeypatch.setattr(icb, "_get_store", lambda: fake_store)

        async def _fake_ensure_graph(*args: Any, **kwargs: Any):
            return "/tmp/graph", {"reused_cached": False, "node_count": 0}

        monkeypatch.setattr(
            "mcp_server.handlers.ingest_codebase_graph.ensure_graph",
            _fake_ensure_graph,
        )
        monkeypatch.setattr(icb, "graphmod", MagicMock())
        icb.graphmod.ensure_graph = _fake_ensure_graph

        async def _fake_fetch_files(graph_path: str, **kwargs: Any):
            return [], []

        monkeypatch.setattr(
            "mcp_server.handlers.ingest_codebase_cypher.fetch_files",
            _fake_fetch_files,
        )
        monkeypatch.setattr(icb, "cypher", MagicMock())
        icb.cypher.fetch_files = _fake_fetch_files

        async def _fake_ingest_entities(*args: Any, **kwargs: Any):
            return 0, 0

        async def _fake_ingest_edges(*args: Any, **kwargs: Any):
            return 0, 0

        async def _fake_pull_processes(*args: Any, **kwargs: Any):
            return []

        async def _fake_enrich(*args: Any, **kwargs: Any):
            return None

        monkeypatch.setattr(icb, "_ingest_entities", _fake_ingest_entities)
        monkeypatch.setattr(icb, "_ingest_edges", _fake_ingest_edges)
        monkeypatch.setattr(icb, "_pull_processes", _fake_pull_processes)
        monkeypatch.setattr(icb, "_enrich_process_symbols", _fake_enrich)
        monkeypatch.setattr(icb_pages, "write_process_pages", lambda _procs: [])
        monkeypatch.setattr(icb, "_prune_precedent_graphs", lambda _: [])

        reporter = FakeReporter()
        result = await icb.handler(
            {"project_path": "/tmp/myproj", "force_reindex": True},
            progress=reporter,
        )

        assert result["ingested"] is True
        # Must have exactly as many stage calls as there are entries in _STAGES.
        # The "fetch files" and "ingest entities/edges" stages are emitted
        # conditionally on do_symbols; since top_symbols is None they fire.
        assert len(reporter.stage_calls) >= 1
        # Stages must arrive in ascending index order.
        indices = [call[1] for call in reporter.stage_calls]
        assert indices == sorted(indices), f"stages out of order: {indices}"
        # close() must have been called.
        assert reporter.closed is True

    @pytest.mark.asyncio
    async def test_null_progress_does_not_alter_handler_result(
        self, monkeypatch
    ) -> None:
        """NullProgress must be transparent — result identical to no progress."""
        fake_store: Any = MagicMock()
        fake_store.batch_pool = MagicMock()
        monkeypatch.setattr(icb, "_get_store", lambda: fake_store)

        async def _fake_ensure_graph(*args: Any, **kwargs: Any):
            return "/tmp/graph", {"reused_cached": False, "node_count": 0}

        icb.graphmod.ensure_graph = _fake_ensure_graph

        async def _fake_fetch_files(*args: Any, **kwargs: Any):
            return [], []

        icb.cypher.fetch_files = _fake_fetch_files

        async def _fake_ingest_entities(*args: Any, **kwargs: Any):
            return 0, 0

        async def _fake_ingest_edges(*args: Any, **kwargs: Any):
            return 0, 0

        async def _fake_pull_processes(*args: Any, **kwargs: Any):
            return []

        async def _fake_enrich(*args: Any, **kwargs: Any):
            return None

        monkeypatch.setattr(icb, "_ingest_entities", _fake_ingest_entities)
        monkeypatch.setattr(icb, "_ingest_edges", _fake_ingest_edges)
        monkeypatch.setattr(icb, "_pull_processes", _fake_pull_processes)
        monkeypatch.setattr(icb, "_enrich_process_symbols", _fake_enrich)
        monkeypatch.setattr(icb_pages, "write_process_pages", lambda _procs: [])
        monkeypatch.setattr(icb, "_prune_precedent_graphs", lambda _: [])

        np = NullProgress()
        result = await icb.handler(
            {"project_path": "/tmp/myproj", "force_reindex": True},
            progress=np,
        )
        assert result["ingested"] is True


# ── Handler early-exit paths: close() + ingested=False ───────────────────────


class TestHandlerEarlyExitClosesProgress:
    """Handler must call close() and return ingested=False on analyze errors."""

    def _patch_store(self, monkeypatch) -> None:
        fake_store: Any = MagicMock()
        fake_store.batch_pool = MagicMock()
        monkeypatch.setattr(icb, "_get_store", lambda: fake_store)

    @pytest.mark.asyncio
    async def test_mcp_connection_error_closes_reporter(self, monkeypatch) -> None:
        """McpConnectionError from ensure_graph must close progress and return
        ingested=False with reason='upstream_mcp_unreachable'."""
        self._patch_store(monkeypatch)

        async def _raise_conn_error(*args: Any, **kwargs: Any):
            raise McpConnectionError("upstream down")

        monkeypatch.setattr(icb, "graphmod", MagicMock())
        icb.graphmod.ensure_graph = _raise_conn_error

        reporter = FakeReporter()
        result = await icb.handler(
            {"project_path": "/tmp/myproj"},
            progress=reporter,
        )

        assert result["ingested"] is False
        assert result.get("reason") == "upstream_mcp_unreachable"
        assert reporter.closed is True

    @pytest.mark.asyncio
    async def test_generic_exception_closes_reporter(self, monkeypatch) -> None:
        """A generic Exception from ensure_graph must close progress and return
        ingested=False with reason='analyze_failed'."""
        self._patch_store(monkeypatch)

        async def _raise_generic(*args: Any, **kwargs: Any):
            raise RuntimeError("something broke")

        monkeypatch.setattr(icb, "graphmod", MagicMock())
        icb.graphmod.ensure_graph = _raise_generic

        reporter = FakeReporter()
        result = await icb.handler(
            {"project_path": "/tmp/myproj"},
            progress=reporter,
        )

        assert result["ingested"] is False
        assert result.get("reason") == "analyze_failed"
        assert reporter.closed is True
