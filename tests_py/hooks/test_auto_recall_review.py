"""Regression coverage for PR #826 native code and security findings."""

from types import SimpleNamespace

import pytest

from mcp_server.core import reranker, reranker_model
from mcp_server.handlers.recall_helpers import filter_low_signal
from mcp_server.hooks import auto_recall
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


@pytest.fixture()
def store(tmp_path):
    backend = SqliteMemoryStore(db_path=str(tmp_path / "recall.db"))
    yield backend
    backend.close()


def seed(store, **values):
    return store.insert_memory(
        {
            "content": "espresso beans in the pantry",
            "heat": 0.8,
            "directory_context": "/repo",
            "capture_origin": "deliberate",
            **values,
        }
    )


@pytest.mark.parametrize("noise", ["network", "local_action", "legacy", "stale"])
def test_ineligible_rows_do_not_spend_either_pool_limit(store, noise):
    target = seed(store)
    # source: candidate_limit(_MAX_MEMORIES) + one row crosses the real pool cap.
    for _index in range(auto_recall.candidate_limit(auto_recall._MAX_MEMORIES) + 1):
        values = {"capture_origin": noise, "heat": 1.0}
        if noise == "legacy":
            values["source"] = "post_tool_capture"
        if noise == "stale":
            values = {"is_stale": True, "heat": 1.0}
        inserted = seed(store, **values)
        if noise == "stale":
            store._conn.execute(
                "UPDATE memories SET is_stale = 1 WHERE id = %s", (inserted,)
            )
            store._conn.commit()
    lexical = store.search_fts(
        '"espresso"',
        limit=1,
        directory_ancestors=["/repo"],
        hook_only=True,
        min_heat=auto_recall._MIN_HEAT,
    )
    hot = store.get_hot_memories(
        limit=1,
        directory_ancestors=["/repo"],
        hook_only=True,
    )
    assert [mid for mid, _ in lexical] == [target]
    assert [row["id"] for row in hot] == [target]


def test_sqlite_recall_projects_legacy_source(store):
    seed(store, capture_origin="legacy", source="post_tool_capture")
    rows = store.recall_memories("espresso", None, max_results=10)
    assert rows and rows[0]["source"] == "post_tool_capture"
    assert filter_low_signal(rows) == ([], len(rows))


@pytest.mark.parametrize("score,expected", [(0.0, []), (1.0, [1])])
def test_real_injection_reranker_abstains_on_irrelevant_scores(
    monkeypatch, score, expected
):
    ranker = SimpleNamespace(rerank=lambda request: [{"id": 0, "score": score}])
    monkeypatch.setattr(reranker, "_ensure_reranker", lambda: ranker)
    result = reranker.rerank_for_injection("question", [(1, 0.01)], {1: "passage"})
    assert result is not None
    assert [mid for mid, _ in result] == expected


def test_inference_failure_is_explicit(monkeypatch):
    notes = []
    monkeypatch.setattr(
        reranker.silent_failure, "note", lambda name, exc: notes.append(name)
    )

    def fail(request):
        raise RuntimeError("inference failed")

    monkeypatch.setattr(
        reranker, "_ensure_reranker", lambda: SimpleNamespace(rerank=fail)
    )
    assert (
        reranker.rerank_for_injection("question", [(1, 0.01)], {1: "passage"}) is None
    )
    assert notes == ["reranker.injection_call"]


@pytest.mark.parametrize("mode", ["missing", "cache_error", "load", "inference"])
def test_degraded_hook_retains_lexical_protected_order_and_diagnostic(
    store, monkeypatch, caplog, mode
):
    ordinary = seed(store)
    protected = seed(store, is_protected=True)
    seed(store, content="unrelated bicycle mechanics")

    def available():
        if mode == "cache_error":
            raise RuntimeError("composition root unavailable")
        return mode != "missing"

    monkeypatch.setattr(reranker_model, "_model_exists", available)
    monkeypatch.setattr(
        reranker,
        "ensure_reranker_loaded",
        lambda: SimpleNamespace(state="failed" if mode == "load" else "loaded"),
    )
    monkeypatch.setattr(reranker, "rerank_for_injection", lambda *args: None)
    rows = auto_recall._recall_memories_sqlite(store, "espresso beans", "/repo")
    assert [row["id"] for row in rows] == [protected, ordinary]
    assert "auto recall degraded" in caplog.text


def test_loaded_hook_abstains_with_empty_semantic_result(store, monkeypatch):
    seed(store, content="unrelated bicycle mechanics")
    monkeypatch.setattr(reranker_model, "_model_exists", lambda: True)
    monkeypatch.setattr(
        reranker, "ensure_reranker_loaded", lambda: SimpleNamespace(state="loaded")
    )
    monkeypatch.setattr(reranker, "rerank_for_injection", lambda *args: [])
    assert auto_recall._recall_memories_sqlite(store, "morning beverage", "/repo") == []


def test_injection_reranker_unavailable_and_empty(monkeypatch):
    monkeypatch.setattr(reranker, "_ensure_reranker", lambda: None)
    assert (
        reranker.rerank_for_injection("question", [(1, 0.01)], {1: "passage"}) is None
    )
    monkeypatch.setattr(reranker, "_ensure_reranker", lambda: SimpleNamespace())
    assert reranker.rerank_for_injection("question", [], {}) == []


def test_incomplete_inference_response_degrades_observably(monkeypatch):
    notes = []
    monkeypatch.setattr(
        reranker.silent_failure, "note", lambda name, exc: notes.append(name)
    )
    ranker = SimpleNamespace(rerank=lambda request: [])
    monkeypatch.setattr(reranker, "_ensure_reranker", lambda: ranker)
    assert (
        reranker.rerank_for_injection("question", [(1, 0.01)], {1: "passage"}) is None
    )
    assert notes == ["reranker.injection_call"]
