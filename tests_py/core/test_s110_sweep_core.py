"""S110 sweep (issue #197, first family): core-layer try/except/pass sites.

Every silent ``except: pass`` in core either became a
``silent_failure.note`` (observable degraded mode) or a typed narrow
handler. Each test forces the guarded operation to fail and asserts the
now-visible signal AND that the pre-existing fallback is unchanged —
same convention as tests_py/core/test_silent_except_sweep_remaining.py.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mcp_server.observability import silent_failure

WARN_LOGGER = "mcp_server.observability.silent_failure"


@pytest.fixture(autouse=True)
def _reset():
    silent_failure.reset()
    yield
    silent_failure.reset()


def _assert_noted(component: str, error_text: str) -> None:
    """Exact-component check via silent_failure.status().

    The caplog asserts pin that a WARNING was emitted; this pins the exact
    component name and that the real exception (not None) was recorded —
    the two mutants a substring-in-message assert lets survive
    (mutation run, scripts/mutation_check.sh, 2026-07-28).
    """
    status = silent_failure.status()
    assert component in status
    assert error_text in str(status[component]["last_error"])


class TestActiveRetrievalReformulate:
    def test_llm_failure_falls_back_to_raw_query_and_is_logged(self, caplog):
        from mcp_server.core.context_assembly.active_retrieval import LLMReformulator

        def broken_llm(prompt: str) -> str:
            raise RuntimeError("model gone")

        ref = LLMReformulator(llm_fn=broken_llm)
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            out = ref.reformulate("when did I mention X?")
        assert out == "when did I mention X?"
        assert any(
            "active_retrieval.llm_reformulate" in r.message for r in caplog.records
        )
        _assert_noted("active_retrieval.llm_reformulate", "model gone")

    def test_llm_success_emits_no_signal(self, caplog):
        from mcp_server.core.context_assembly.active_retrieval import LLMReformulator

        ref = LLMReformulator(llm_fn=lambda prompt: "rewritten")
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            assert ref.reformulate("q") == "rewritten"
        assert not caplog.records


class TestResolveQueryEntityIds:
    def test_keyword_stage_failure_keeps_stage1_ids_and_is_logged(
        self, caplog, monkeypatch
    ):
        from mcp_server.core import recall_pipeline

        # Patch the consumer's own bindings: both imports are at module top
        # (#197 family 4), so patching the defining modules no longer
        # reaches the already-bound references.
        monkeypatch.setattr(
            recall_pipeline, "extract_query_entities", lambda q: ["Alpha"]
        )

        def broken_keywords(query: str):
            raise RuntimeError("tokenizer exploded")

        monkeypatch.setattr(recall_pipeline, "extract_keywords", broken_keywords)
        store = MagicMock()
        store.get_entity_by_name.return_value = {"id": 7}
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            ids = recall_pipeline._resolve_query_entity_ids("some query", store)
        assert ids == {7}
        assert any(
            "recall_pipeline.keyword_entity_fallback" in r.message
            for r in caplog.records
        )
        _assert_noted("recall_pipeline.keyword_entity_fallback", "tokenizer exploded")


class TestReconsolidationApplyWritebacks:
    @staticmethod
    def _outcome(**kwargs):
        base = {
            "action": "reconsolidate",
            "heat_delta": 0.0,
            "valence_delta": 0.0,
            "update_last_accessed": False,
        }
        base.update(kwargs)
        return SimpleNamespace(**base)

    @staticmethod
    def _candidates():
        return [{"memory_id": 1, "heat": 0.5, "emotional_valence": 0.0}]

    def _run(self, monkeypatch, outcome, store):
        from mcp_server.core import recall_pipeline
        from mcp_server.core.recall_pipeline import reconsolidation_apply

        # Patch the consumer's own binding (top-level import, #197 family 4).
        monkeypatch.setattr(
            recall_pipeline,
            "compute_reconsolidation_action",
            lambda *a, **k: outcome,
        )
        return reconsolidation_apply(self._candidates(), "query", store)

    def test_heat_writeback_failure_is_logged(self, caplog, monkeypatch):
        store = MagicMock(spec=["bump_heat_raw"])
        store.bump_heat_raw.side_effect = RuntimeError("pg down")
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            out = self._run(monkeypatch, self._outcome(heat_delta=0.2), store)
        assert len(out) == 1
        assert any(
            "recall_pipeline.heat_writeback" in r.message for r in caplog.records
        )
        _assert_noted("recall_pipeline.heat_writeback", "pg down")

    def test_access_writeback_failure_is_logged(self, caplog, monkeypatch):
        store = MagicMock(spec=["update_memory_access"])
        store.update_memory_access.side_effect = RuntimeError("pg down")
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            out = self._run(
                monkeypatch, self._outcome(update_last_accessed=True), store
            )
        assert len(out) == 1
        assert any(
            "recall_pipeline.access_writeback" in r.message for r in caplog.records
        )
        _assert_noted("recall_pipeline.access_writeback", "pg down")

    def test_valence_writeback_failure_is_logged(self, caplog, monkeypatch):
        store = MagicMock(spec=["update_memory_emotional_valence"])
        store.update_memory_emotional_valence.side_effect = RuntimeError("pg down")
        with caplog.at_level("WARNING", logger=WARN_LOGGER):
            out = self._run(monkeypatch, self._outcome(valence_delta=0.3), store)
        assert len(out) == 1
        assert any(
            "recall_pipeline.valence_writeback" in r.message for r in caplog.records
        )
        _assert_noted("recall_pipeline.valence_writeback", "pg down")


class TestJsonNativeTolistFallback:
    def test_tolist_failure_stringifies_and_logs_debug(self, caplog):
        from mcp_server.shared.json_native import to_json_native

        class Exotic:
            def tolist(self):
                raise RuntimeError("not a real array")

            def __str__(self) -> str:
                return "<exotic>"

        with caplog.at_level("DEBUG", logger="mcp_server.shared.json_native"):
            assert to_json_native(Exotic()) == "<exotic>"
        assert any("tolist() conversion failed" in r.message for r in caplog.records)


class TestToolErrorHandlerGuards:
    def test_fresh_loop_close_runtimeerror_is_swallowed(self, monkeypatch):
        from mcp_server import tool_error_handler

        async def handler(args):
            return {"ok": True}

        fake_loop = MagicMock()
        fake_loop.run_until_complete.side_effect = lambda coro: (
            coro.close(),
            {"ok": True},
        )[1]
        fake_loop.close.side_effect = RuntimeError("loop still running")
        monkeypatch.setattr(
            tool_error_handler.asyncio, "new_event_loop", lambda: fake_loop
        )
        result = tool_error_handler._run_coroutine_on_thread(handler, {})
        assert result == {"ok": True}
        fake_loop.close.assert_called_once()

    def test_metrics_failure_logs_debug_and_keeps_error_chain(
        self, caplog, monkeypatch
    ):
        """Regression (this PR): the inner metrics guard used to rebind
        ``exc``, unbinding the outer exception before ``raise ... from exc``
        — the ToolError below would have become an UnboundLocalError."""
        from fastmcp.exceptions import ToolError

        from mcp_server import tool_error_handler
        from mcp_server.observability import metrics

        async def broken_handler(args):
            raise ValueError("handler bug")

        def broken_counter(*a, **k):
            raise RuntimeError("prometheus gone")

        monkeypatch.setattr(metrics, "inc_counter", broken_counter)
        with caplog.at_level("DEBUG", logger="mcp_server.tool_error_handler"):
            with pytest.raises(ToolError) as excinfo:
                asyncio.run(
                    tool_error_handler.safe_handler(
                        broken_handler, {}, tool_name="recall"
                    )
                )
        assert isinstance(excinfo.value.__cause__, ValueError)
        assert any(
            "error-counter increment failed" in r.message for r in caplog.records
        )


class TestMcpProgressDispatch:
    def test_dispatch_on_closed_loop_is_dropped(self):
        from mcp_server.mcp_progress import McpProgress

        loop = asyncio.new_event_loop()
        loop.close()
        progress = McpProgress(ctx=MagicMock(), loop=loop)

        async def _noop():
            return None

        # Must neither raise nor leak an un-awaited coroutine warning.
        progress._dispatch(_noop())
