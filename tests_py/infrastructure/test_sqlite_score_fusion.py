"""SQLite recall fuses max-normalised scores, as PL/pgSQL ``recall_memories`` does.

The vector signal must arrive as cosine similarity (sqlite-vec returns L2
distance), be shifted by +1 before normalisation, and the fused score of a
memory must be the weighted sum of its per-signal scores over the pool maxima.
"""

from __future__ import annotations

import numpy as np
import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from mcp_server.infrastructure.sqlite_store_search import _normalised

_DIM = 384
_DOMAIN = "sqlite-score-fusion-test"


def _unit(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).standard_normal(_DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def _at_cosine(base: np.ndarray, cosine: float, seed: int) -> bytes:
    other = _unit(seed)
    other -= other.dot(base) * base
    other /= np.linalg.norm(other)
    mixed = cosine * base + np.sqrt(1.0 - cosine**2) * other
    return mixed.astype(np.float32).tobytes()


def _payload(content: str, embedding: bytes) -> dict:
    return {
        "content": content,
        "domain": _DOMAIN,
        "embedding": embedding,
        "heat_base": 1.0,
        "tags": [],
        "source": "test",
    }


@pytest.fixture
def store():
    s = SqliteMemoryStore()
    yield s
    s.close()


class TestNormalised:
    def test_plain_signal_is_divided_by_its_maximum(self):
        assert _normalised({1: 4.0, 2: 2.0}, weight=0.5) == {1: 0.5, 2: 0.25}

    def test_cosine_is_shifted_by_one_before_normalisation(self):
        out = _normalised({1: 1.0, 2: 0.0, 3: -1.0}, weight=1.0, shift=-1.0)
        assert out == {1: 1.0, 2: 0.5, 3: 0.0}

    def test_empty_pool_contributes_nothing(self):
        assert _normalised({}, weight=1.0) == {}

    def test_non_positive_maximum_is_floored(self):
        out = _normalised({1: 0.0}, weight=1.0)
        assert out == {1: 0.0}


class TestVectorSignal:
    def test_signal_is_cosine_similarity(self, store):
        base = _unit(0)
        for i, cosine in enumerate((0.9, 0.5, 0.1)):
            store.insert_memory(_payload(f"m{i}", _at_cosine(base, cosine, 10 + i)))
        raw = store._signal_vector(base.tobytes(), weight=1.0, pool=10)
        assert sorted(raw.values(), reverse=True) == pytest.approx(
            [0.9, 0.5, 0.1], abs=1e-4
        )


class TestFusedScore:
    def test_vector_only_score_is_shifted_cosine_over_pool_maximum(self, store):
        base = _unit(0)
        for i, cosine in enumerate((0.9, 0.5)):
            store.insert_memory(_payload(f"m{i}", _at_cosine(base, cosine, 10 + i)))
        rows = store.recall_memories(
            query_text="",
            query_embedding=base.tobytes(),
            domain=_DOMAIN,
            min_heat=0.0,
            weights={"vector": 1.0, "fts": 0.0, "heat": 0.0, "recency": 0.0},
        )
        scores = {r["content"]: r["score"] for r in rows}
        assert scores["m0"] == pytest.approx(1.0, abs=1e-4)
        assert scores["m1"] == pytest.approx((0.5 + 1.0) / (0.9 + 1.0), abs=1e-4)

    def test_weights_scale_each_signal_contribution(self, store):
        base = _unit(0)
        store.insert_memory(_payload("only", _at_cosine(base, 0.8, 10)))
        rows = store.recall_memories(
            query_text="",
            query_embedding=base.tobytes(),
            domain=_DOMAIN,
            min_heat=0.0,
            weights={"vector": 0.7, "fts": 0.0, "heat": 0.3, "recency": 0.0},
        )
        assert rows[0]["score"] == pytest.approx(0.7 + 0.3, abs=1e-4)

    def test_recency_is_off_by_default_and_orders_when_enabled(self, store):
        base = _unit(0)
        old = _payload("old", _at_cosine(base, 0.5, 10))
        old["created_at"] = "2020-01-01T00:00:00+00:00"
        new = _payload("new", _at_cosine(base, 0.5, 11))
        new["created_at"] = "2026-01-01T00:00:00+00:00"
        store.insert_memory(old)
        store.insert_memory(new)
        recency = store._signal_recency(
            weight=1.0, pool=10, min_heat=0.0, domain=_DOMAIN, directory=None
        )
        by_content = {
            r["content"]: recency[r["id"]]
            for r in store._conn.execute("SELECT id, content FROM memories").fetchall()
        }
        assert by_content["new"] > by_content["old"]
        assert (
            store._signal_recency(
                weight=0.0, pool=10, min_heat=0.0, domain=_DOMAIN, directory=None
            )
            == {}
        )
