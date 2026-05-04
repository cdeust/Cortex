"""Verify ``standard_rag`` issues the expected SQL with the right params.

This is NOT a live PG test. We feed a fake psycopg connection / cursor and
assert the SQL matches the vanilla cosine top-k contract from protocol §2.B
and that the bound parameters are a 384-dim numpy float32 vector (not raw
bytes, not a string). Production uses ``register_vector`` on the connection,
so the adapter handles numpy → ``vector`` binding without an explicit cast.

Companion to ``test_beam_standard_rag.py`` (which audits the source AST).
This test exercises the runtime path with a mock store.
"""

from __future__ import annotations

import numpy as np
import pytest

from benchmarks.llm_head_to_head import retriever_baselines


class _FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self._rows = rows

    def execute(self, sql: str, params: tuple) -> None:
        self.executed.append((sql, params))

    def fetchall(self) -> list[tuple]:
        return self._rows

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _FakeConn:
    def __init__(self, rows: list[tuple]) -> None:
        self._cursor = _FakeCursor(rows)

    def cursor(self) -> _FakeCursor:
        return self._cursor


class _FakeBenchmarkDB:
    def __init__(self, rows: list[tuple]) -> None:
        self.conn = _FakeConn(rows)


class _FakeEmbeddingEngine:
    """Returns a deterministic 384-dim float32 byte blob for any input."""

    DIM = 384

    def encode(self, text: str) -> bytes:
        rng = np.random.default_rng(seed=hash(text) & 0x7FFFFFFF)
        vec = rng.standard_normal(self.DIM).astype(np.float32)
        # L2-normalise so cosine math is meaningful (matches production).
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        return vec.tobytes()


@pytest.fixture
def patch_embedding(monkeypatch: pytest.MonkeyPatch) -> _FakeEmbeddingEngine:
    eng = _FakeEmbeddingEngine()
    monkeypatch.setattr(retriever_baselines, "get_embedding_engine", lambda: eng)
    return eng


def test_standard_rag_issues_cosine_topk_query(patch_embedding) -> None:
    """SQL must reference ``embedding`` cosine operator and ``LIMIT %s``."""
    fake_rows = [
        (1, "memory body 1", 0.10),  # cosine_dist = 0.10 → cosine_sim = 0.90
        (2, "memory body 2", 0.30),
        (3, "memory body 3", 0.50),
    ]
    db = _FakeBenchmarkDB(fake_rows)
    out = retriever_baselines.standard_rag(
        "what is the capital of france?", db, top_k=3
    )

    assert len(out) == 3
    assert out[0].memory_id == 1
    assert out[0].content == "memory body 1"
    # cosine_sim = 1 - cosine_dist
    assert abs(out[0].cosine - 0.90) < 1e-6

    sql, params = db.conn._cursor.executed[0]
    sql_lower = sql.lower()
    assert "embedding" in sql_lower
    assert "<=>" in sql_lower
    assert "limit %s" in sql_lower
    # The forbidden Cortex columns must NOT appear.
    for col in ("heat", "access_count", "replay_count"):
        assert col not in sql_lower, f"{col} leaked into vanilla RAG SQL"

    # Params: (qvec, qvec, top_k). The first two must be 384-dim float32
    # numpy arrays (the pgvector adapter needs numpy, not bytes).
    assert len(params) == 3
    qvec_a, qvec_b, k = params
    assert isinstance(qvec_a, np.ndarray)
    assert qvec_a.dtype == np.float32
    assert qvec_a.shape == (384,)
    assert qvec_b is qvec_a or np.array_equal(qvec_b, qvec_a)
    assert k == 3


def test_standard_rag_handles_dict_row_factory(patch_embedding) -> None:
    """psycopg's dict_row factory yields dicts, not tuples — must not crash."""
    fake_rows = [
        {"id": 7, "content": "row body", "cdist": 0.20},
    ]
    db = _FakeBenchmarkDB(fake_rows)
    out = retriever_baselines.standard_rag("question", db, top_k=1)
    assert len(out) == 1
    assert out[0].memory_id == 7
    assert out[0].content == "row body"
    assert abs(out[0].cosine - 0.80) < 1e-6


def test_standard_rag_resolves_store_conn(patch_embedding) -> None:
    """BenchmarkDB exposes ``._store._conn``; the resolver must find it."""
    fake_rows = [(99, "via store", 0.05)]
    fake_store = type("S", (), {"_conn": _FakeConn(fake_rows)})()
    db = type("DB", (), {"_store": fake_store})()
    out = retriever_baselines.standard_rag("q", db, top_k=1)
    assert len(out) == 1
    assert out[0].memory_id == 99


def test_standard_rag_empty_question_returns_empty(patch_embedding) -> None:
    db = _FakeBenchmarkDB([])
    assert retriever_baselines.standard_rag("", db) == []
    assert retriever_baselines.standard_rag("   ", db) == []
