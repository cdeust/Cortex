"""W0-1: count model work without changing results or leaking across calls."""

from __future__ import annotations

import asyncio
from unittest.mock import Mock

from mcp_server.core import reranker, retrieval_dispatch
from mcp_server.shared.telemetry_context import (
    count_reranked,
    operation_metrics,
    retrieval_metrics,
    set_retrieval_tier,
)


def test_metrics_are_nested_and_task_local():
    async def collect(tier, count):
        with operation_metrics() as measured:
            set_retrieval_tier(tier)
            count_reranked(count)
            await asyncio.sleep(0)
            with operation_metrics() as nested:
                assert nested.tier is None
                count_reranked(1)
            assert retrieval_metrics() is measured
            return measured.tier, measured.reranked_count

    async def run():
        return await asyncio.gather(collect("simple", 2), collect("deep", 3))

    assert asyncio.run(run()) == [("simple", 2), ("deep", 3)]
    assert retrieval_metrics().reranked_count == 0
    assert retrieval_metrics().tier is None


def test_successful_reranking_counts_input_and_preserves_result(monkeypatch):
    model = Mock()
    model.rerank.return_value = [{"id": 0, "score": 0.9}, {"id": 1, "score": 0.8}]
    monkeypatch.setattr(reranker, "_ensure_reranker", lambda: model)
    candidates = [(1, 0.7), (2, 0.6)]
    content = {1: "first", 2: "second"}
    uninstrumented = reranker.rerank_results("query", candidates, content)
    with operation_metrics() as measured:
        instrumented = reranker.rerank_results("query", candidates, content)
    assert instrumented == uninstrumented
    assert measured.reranked_count == len(model.rerank.call_args.args[0].passages)


def test_skipped_or_failed_model_is_not_counted(monkeypatch, caplog):
    monkeypatch.setattr(reranker, "_ensure_reranker", lambda: None)
    with operation_metrics() as measured:
        assert reranker.rerank_results("q", [(1, 0.5)], {}) == [(1, 0.5)]
        assert measured.reranked_count == 0
    model = Mock()
    model.rerank.side_effect = RuntimeError("fixture inference failure")
    monkeypatch.setattr(reranker, "_ensure_reranker", lambda: model)
    with operation_metrics() as measured:
        assert reranker.rerank_results("q", [(1, 0.5)], {}) == [(1, 0.5)]
        assert measured.reranked_count == 0
    assert "fixture inference failure" in caplog.text


def test_legacy_dispatch_records_executed_tier_without_changing_output(monkeypatch):
    monkeypatch.setattr(retrieval_dispatch, "rerank_results", lambda q, p, c: p)
    args = ("q", {"vector": [(1, 0.5)]}, {"intent": "general"}, {1: "text"})
    original = retrieval_dispatch.dispatch_retrieval(*args)
    with operation_metrics() as measured:
        observed = retrieval_dispatch.dispatch_retrieval(*args)
    assert observed == original
    assert measured.tier == observed[1]
