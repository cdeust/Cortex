"""Issue #706 regression: rerank low-overlap candidates before the injection cut."""

from types import SimpleNamespace

import pytest

from mcp_server.core import reranker, reranker_model
from mcp_server.hooks import auto_recall
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


@pytest.fixture()
def store(tmp_path):
    result = SqliteMemoryStore(db_path=str(tmp_path / "memory.db"))
    yield result
    result.close()


def test_paraphrase_reaches_reranker_before_top_three_cut(store, monkeypatch):
    target = store.insert_memory(
        {
            "content": "The pantry contains espresso beans.",
            "capture_origin": "deliberate", "heat": 0.8,
            "directory_context": "/repo",
        }
    )
    for index in range(10):
        store.insert_memory(
            {
                "content": f"Morning beverage query logging record {index}",
                "capture_origin": "deliberate", "heat": 0.9,
                "directory_context": "/repo",
            }
        )
    calls = []

    def rank(query, candidates, contents):
        calls.append((query, list(contents)))
        return sorted(candidates, key=lambda pair: pair[0] != target)

    monkeypatch.setattr(reranker_model, "_model_exists", lambda: True)
    monkeypatch.setattr(
        reranker, "ensure_reranker_loaded", lambda: SimpleNamespace(state="loaded")
    )
    monkeypatch.setattr(reranker, "rerank_for_injection", rank)
    rows = auto_recall._recall_memories_sqlite(store, "morning beverage", "/repo")
    assert rows[0]["id"] == target
    assert len(rows) == auto_recall._MAX_MEMORIES
    assert calls and target in calls[0][1]


def test_missing_model_does_not_inject_heat_only_candidates(store, monkeypatch):
    store.insert_memory(
        {
            "content": "The pantry contains espresso beans.",
            "capture_origin": "deliberate", "heat": 0.8,
            "directory_context": "/repo",
        }
    )
    monkeypatch.setattr(reranker_model, "_model_exists", lambda: False)
    assert auto_recall._recall_memories_sqlite(store, "morning beverage", "/repo") == []


def test_rerank_failure_does_not_inject_heat_only_candidates(store, monkeypatch):
    store.insert_memory(
        {
            "content": "The pantry contains espresso beans.",
            "capture_origin": "deliberate", "heat": 0.8,
            "directory_context": "/repo",
        }
    )
    monkeypatch.setattr(reranker_model, "_model_exists", lambda: True)
    monkeypatch.setattr(
        reranker, "ensure_reranker_loaded", lambda: SimpleNamespace(state="loaded")
    )
    monkeypatch.setattr(
        reranker, "rerank_for_injection", lambda query, pairs, texts: None
    )
    assert auto_recall._recall_memories_sqlite(store, "morning beverage", "/repo") == []


def test_hot_pool_failure_preserves_lexical_recall(store, monkeypatch):
    target = store.insert_memory(
        {
            "content": "espresso beans for the pantry",
            "capture_origin": "deliberate", "heat": 0.8,
            "directory_context": "/repo",
        }
    )

    def unavailable(**kwargs):
        raise OSError("hot pool read failed")

    monkeypatch.setattr(store, "get_hot_memories", unavailable)
    monkeypatch.setattr(reranker_model, "_model_exists", lambda: True)
    monkeypatch.setattr(
        reranker, "ensure_reranker_loaded", lambda: SimpleNamespace(state="loaded")
    )
    monkeypatch.setattr(
        reranker, "rerank_for_injection", lambda query, pairs, texts: list(pairs)
    )
    rows = auto_recall._recall_memories_sqlite(store, "espresso beans", "/repo")
    assert [row["id"] for row in rows] == [target]
