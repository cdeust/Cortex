"""Issue #706: the hook abstains and ranks by embedding similarity, not CE score."""

from types import SimpleNamespace

import numpy as np
import pytest

from mcp_server.core import reranker, reranker_model
from mcp_server.core.injection_relevance import (
    INJECTION_SIMILARITY_FLOOR,
    relevant_by_similarity,
)
from mcp_server.hooks import auto_recall, auto_recall_ranking
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

# source: all-MiniLM-L6-v2 output dimension (the stored vector width).
_DIM = 384


def _vector(cosine_to_axis0: float) -> np.ndarray:
    """Unit vector whose cosine with axis 0 is ``cosine_to_axis0``."""
    vector = np.zeros(_DIM, dtype=np.float32)
    vector[0] = cosine_to_axis0
    vector[1] = np.sqrt(1.0 - cosine_to_axis0**2)
    return vector


_QUERY = _vector(1.0)


@pytest.fixture()
def store(tmp_path):
    backend = SqliteMemoryStore(db_path=str(tmp_path / "semantic.db"))
    if not backend._has_vec:
        pytest.skip("stored vectors require sqlite-vec")
    yield backend
    backend.close()


@pytest.fixture()
def loaded(monkeypatch):
    """Both cached models present; CE scores keep the similarity order."""
    monkeypatch.setattr(reranker_model, "_model_exists", lambda: True)
    monkeypatch.setattr(
        reranker, "ensure_reranker_loaded", lambda: SimpleNamespace(state="loaded")
    )
    # Every CE score below ADR-0245's gate: only similarity admits a row.
    monkeypatch.setattr(
        reranker,
        "rerank_for_injection",
        lambda query, pairs, texts, admitted: [p for p in pairs if p[0] in admitted],
    )
    monkeypatch.setattr(
        auto_recall_ranking, "cached_query_encoder", lambda: lambda text: _QUERY
    )


def _recall(store, prompt):
    return auto_recall._recall_memories_sqlite(store, prompt, "/repo")


def _seed(store, content, cosine, **overrides):
    return store.insert_memory(
        {
            "content": content,
            "heat": 0.9,
            "directory_context": "/repo",
            "capture_origin": "deliberate",
            "embedding": _vector(cosine).tobytes(),
            "embedding_model": "neural",
            **overrides,
        }
    )


def test_floor_orders_by_similarity_and_drops_unrelated():
    vectors = {1: _vector(0.3), 2: _vector(0.9), 3: _vector(0.1)}
    assert relevant_by_similarity(_QUERY, vectors) == [2, 1]
    # source: hosted bounds 0.235 (lowest positive) / 0.152 (highest negative).
    assert 0.152 < INJECTION_SIMILARITY_FLOOR < 0.235


def test_unrelated_prompt_injects_no_hot_memory(store, loaded):
    for index in range(5):
        _seed(store, f"Bicycle chain maintenance note {index}", 0.1, heat=1.0)
    assert _recall(store, "kaon quark makeup") == []


def test_paraphrase_without_lexical_overlap_is_injected(store, loaded):
    target = _seed(store, "The pantry contains espresso beans.", 0.45, heat=0.5)
    for index in range(5):
        _seed(store, f"Bicycle chain maintenance note {index}", 0.1, heat=1.0)
    rows = _recall(store, "stimulating morning drink")
    assert [row["id"] for row in rows] == [target]


def test_fallback_space_vectors_never_qualify(store, loaded):
    _seed(store, "Espresso beans.", 0.99, embedding_model="fallback")
    assert _recall(store, "stimulating drink") == []


def test_absent_query_encoder_degrades_to_lexical(store, loaded, monkeypatch, caplog):
    lexical = _seed(store, "espresso beans in the pantry", 0.1)
    monkeypatch.setattr(auto_recall_ranking, "cached_query_encoder", lambda: None)
    rows = auto_recall._recall_memories_sqlite(store, "espresso beans", "/repo")
    assert [row["id"] for row in rows] == [lexical]
    assert "semantic relevance unavailable" in caplog.text


def test_postgres_vectors_are_one_bounded_lookup():
    statements = []

    class Connection:
        def execute(self, statement, params):
            statements.append((statement, params))
            return self

        def fetchall(self):
            return [{"id": 7, "embedding": [1.0, 0.0]}]

    assert auto_recall._pg_vectors(Connection(), [7, 8]) == {7: [1.0, 0.0]}
    assert "ANY(%s::int[])" in statements[0][0]
    assert statements[0][1] == ([7, 8],)
