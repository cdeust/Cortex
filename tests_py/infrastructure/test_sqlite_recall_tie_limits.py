"""SQLite recall keeps a tie group of any size within SQLite's hard limits.

ADR-1109 keeps a signal's whole boundary tie group, so a group can hold every
memory. Two engine limits stood in the way at 7293672d (review of #760):

- sqlite-vec refuses a KNN k above 4096 (``SQLITE_VEC_VEC0_K_MAX``); growing
  k to read a boundary group failed, and the vector signal was dropped
  silently. The KNN now asks for ``pool + 1`` rows only and reads the rest of
  the group with an exact distance query.
- a statement binding one parameter per id fails past the build's
  ``SQLITE_MAX_VARIABLE_NUMBER`` (``too many SQL variables``). Id sets are now
  one JSON array (``json_each``); here the limit is lowered to 999.

source: ADR-1109
"""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from mcp_server.infrastructure.sqlite_store_recall_signals import VEC0_K_MAX

# source: sqlite_schema.py memories_vec embedding float[384]
_DIM = 384
_DOMAIN = "tie-limits"
_VECTOR_ONLY = {"vector": 1.0, "fts": 0.0, "heat": 0.0, "recency": 0.0}
# source: handlers/recall.py schema maximum max_results 100 -> top_k 300 ->
# store pool 300 * 10 = 3000 (review of #760, B1).
_LARGE_POOL = 3000
# source: review of #760, B1 -- 3,300 identical vectors pass the old doubling
# (101 -> ... -> 3232 -> 6464 > 4096) at the default pool of 100.
_IDENTICAL = 3300
# source: review of #760, B2 -- 1,200 tied rows against a limit of 999.
_TIED, _VARIABLE_LIMIT = 1200, 999


@pytest.fixture
def store():
    s = SqliteMemoryStore()
    if not s._has_vec:
        pytest.fail("sqlite-vec must be loaded")
    yield s
    s.close()


def _scaled_axis(scale: float) -> bytes:
    v = np.zeros(_DIM, dtype=np.float32)
    v[0] = scale
    return v.tobytes()


def _insert(store: SqliteMemoryStore, embedding: bytes | None, n: int = 1) -> None:
    for _ in range(n):
        store.insert_memory(
            {
                "content": "zq row",
                "embedding": embedding,
                "domain": _DOMAIN,
                "source": "lesson",
                "heat": 0.5,
            }
        )


def test_vector_boundary_group_past_k_max_is_kept(store):
    """2,999 rows at distinct distances, two identical ones at the boundary of
    a 3,000-row pool: every row gets vector credit, none is dropped."""
    for i in range(_LARGE_POOL - 1):
        _insert(store, _scaled_axis(1.0 + 0.001 * i))
    _insert(store, _scaled_axis(1.0 + 0.001 * _LARGE_POOL), n=2)
    scores: dict[int, float] = {}
    store._signal_vector(scores, _scaled_axis(1.0), 1.0, 60, _LARGE_POOL)
    assert len(scores) == _LARGE_POOL + 1
    tied = sorted(scores.values())[:2]
    assert tied[0] == tied[1]


def test_identical_embeddings_beyond_k_max_all_score(store):
    _insert(store, _scaled_axis(1.0), n=_IDENTICAL)
    scores: dict[int, float] = {}
    store._signal_vector(scores, _scaled_axis(2.0), 1.0, 60, 100)
    assert len(scores) == _IDENTICAL
    assert len(set(scores.values())) == 1
    rows = store.recall_memories(
        query_text="nothingmatches",
        query_embedding=_scaled_axis(2.0),
        domain=_DOMAIN,
        min_heat=0.0,
        max_results=10,
        weights=_VECTOR_ONLY,
    )
    assert len(rows) == 30


def test_vector_pool_above_k_max_raises(store):
    _insert(store, _scaled_axis(1.0))
    with pytest.raises(ValueError, match="KNN limit 4096"):
        store._signal_vector({}, _scaled_axis(1.0), 1.0, 60, VEC0_K_MAX)


def test_vector_signal_failure_is_not_swallowed(store):
    _insert(store, _scaled_axis(1.0))
    with pytest.raises(sqlite3.Error):
        store._signal_vector({}, np.zeros(_DIM + 1, np.float32).tobytes(), 1.0, 60, 10)


@pytest.mark.parametrize(
    "extra",
    [{}, {"agent_topic": "t"}, {"untrusted_factor": 0.5}],
    ids=["plain", "agent-boost", "trust-factor"],
)
def test_tie_group_above_the_variable_limit(store, extra):
    _insert(store, None, n=_TIED)
    store._connection_registry.connection().setlimit(
        sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, _VARIABLE_LIMIT
    )
    rows = store.recall_memories(
        query_text="nothingmatches",
        query_embedding=None,
        domain=_DOMAIN,
        min_heat=0.0,
        max_results=10,
        weights={"vector": 0.0, "fts": 0.0, "heat": 1.0, "recency": 0.0},
        **extra,
    )
    assert len(rows) == 30
