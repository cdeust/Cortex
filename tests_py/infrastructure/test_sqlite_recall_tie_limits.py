"""SQLite recall keeps a tie group of any size within SQLite's hard limits.

ADR-1109 keeps a signal's whole boundary tie group, so a group can hold every
memory. Engine limits met by earlier heads of #760:

- sqlite-vec refuses a KNN k above 4096 (``SQLITE_VEC_VEC0_K_MAX``). The KNN
  serves k up to the cap; a pool needing more (``max_results`` >= 410, reached
  through ``unified_search(max_results=69)``) or a boundary group still open
  at the cap is read with the scalar ``vec_distance_l2``.
- one bind parameter per id fails past the build's ``SQLITE_MAX_VARIABLE_NUMBER``.
  Id sets are one JSON array (``json_each``); the test counts the placeholders
  of every statement and requires the maximum not to grow with the group.

source: ADR-1109
"""

from __future__ import annotations

import asyncio
import sqlite3

import numpy as np
import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from mcp_server.infrastructure.sqlite_store_recall_signals import VEC0_K_MAX

# source: sqlite_schema.py memories_vec embedding float[384]
_DIM = 384
_DOMAIN = "tie-limits"
_VECTOR_ONLY = {"vector": 1.0, "fts": 0.0, "heat": 0.0, "recency": 0.0}
_HEAT_ONLY = {"vector": 0.0, "fts": 0.0, "heat": 1.0, "recency": 0.0}
# source: handlers/recall.py schema maximum max_results 100 -> top_k 300 ->
# store pool 300 * 10 = 3000 (review 1 of #760, B1).
_LARGE_POOL = 3000
# source: review 1 of #760, B1 -- 3,300 identical vectors pass the old
# doubling (101 -> ... -> 3232 -> 6464 > 4096) at the default pool of 100.
_IDENTICAL = 3300
# source: review 2 of #760, N1 -- pool = max_results * 10 needs k = 4101.
_ABOVE_CAP_RESULTS = 410
# source: review 2 of #760, N1 -- unified_search max 69 -> recall 138 ->
# fetch_k 414 -> pool 4140.
_UNIFIED_MAX = 69
# source: test fixture -- a 50-row store; two tie groups both past the pool
# of 100 (so both take the tie-group path), 1,200 > 999, the variable limit
# review 1 used.
_SMALL = 50
_GROUP_SMALL, _GROUP_LARGE = 150, 1200


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
                "agent_context": "t",
            }
        )


def _recall(store: SqliteMemoryStore, weights: dict, **kw) -> list[dict]:
    return store.recall_memories(
        query_text="nothingmatches",
        domain=_DOMAIN,
        min_heat=0.0,
        weights=weights,
        **{"query_embedding": None, "max_results": 10, **kw},
    )


def test_vector_boundary_group_past_k_max_is_kept(store):
    """2,999 rows at distinct distances, two identical ones at the boundary of
    a 3,000-row pool: every row gets vector credit, none is dropped."""
    for i in range(_LARGE_POOL - 1):
        _insert(store, _scaled_axis(1.0 + 0.001 * i))
    _insert(store, _scaled_axis(1.0 + 0.001 * _LARGE_POOL), n=2)
    credits = store._signal_vector(_scaled_axis(1.0), 1.0, 60, _LARGE_POOL)
    assert len(credits) == _LARGE_POOL + 1
    tied = sorted(c for _, c in credits)[:2]
    assert tied[0] == tied[1]


def test_identical_embeddings_beyond_k_max_all_score(store):
    _insert(store, _scaled_axis(1.0), n=_IDENTICAL)
    credits = store._signal_vector(_scaled_axis(2.0), 1.0, 60, 100)
    assert len(credits) == _IDENTICAL
    assert len({c for _, c in credits}) == 1
    rows = _recall(store, _VECTOR_ONLY, query_embedding=_scaled_axis(2.0))
    assert len(rows) == 30


def test_vector_pool_above_k_max_reads_the_scalar_distance(store):
    """A 50-row store at max_results 410 (pool 4100 > 4096 - 1): every row
    is scored, in the same order as the KNN ranks them."""
    for i in range(_SMALL):
        _insert(store, _scaled_axis(1.0 + 0.01 * i))
    above = store._signal_vector(_scaled_axis(1.0), 1.0, 60, VEC0_K_MAX)
    below = store._signal_vector(_scaled_axis(1.0), 1.0, 60, 100)
    assert above == below and len(above) == _SMALL
    rows = _recall(
        store, _VECTOR_ONLY, query_embedding=_scaled_axis(1.0), max_results=410
    )
    assert len(rows) == _SMALL


def test_vector_signal_failure_is_not_swallowed(store):
    _insert(store, _scaled_axis(1.0))
    with pytest.raises(sqlite3.Error):
        store._signal_vector(np.zeros(_DIM + 1, np.float32).tobytes(), 1.0, 60, 10)


class _PlaceholderCounter:
    """Delegating connection that records each statement's ``?`` count."""

    def __init__(self, real) -> None:
        self._real = real
        self.counts: list[int] = []

    def execute(self, sql, *args, **kwargs):
        self.counts.append(sql.count("?"))
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _max_placeholders(store: SqliteMemoryStore, n: int, extra: dict) -> int:
    _insert(store, None, n=n)
    counter = _PlaceholderCounter(store._conn)
    store._conn = counter
    try:
        rows = _recall(store, _HEAT_ONLY, **extra)
    finally:
        store._conn = counter._real
    assert len(rows) == 30
    return max(counter.counts)


@pytest.mark.parametrize(
    "extra",
    [{}, {"agent_topic": "t"}, {"untrusted_factor": 0.5}],
    ids=["plain", "agent-boost", "trust-factor"],
)
def test_no_statement_binds_one_variable_per_tied_row(extra):
    """The most placeholders any statement binds is the same for a 150-row
    and a 1,200-row tie group: no statement depends on the group's size,
    so none can reach the build's bind-variable limit."""
    small, large = SqliteMemoryStore(), SqliteMemoryStore()
    try:
        assert _max_placeholders(small, _GROUP_SMALL, extra) == _max_placeholders(
            large, _GROUP_LARGE, extra
        )
    finally:
        small.close()
        large.close()


def test_unified_search_above_the_k_cap_returns_results(monkeypatch, store):
    """unified_search(max_results=69) asks the store for a pool of 4140."""
    from mcp_server.handlers import recall, unified_search
    from mcp_server.infrastructure.embedding_engine import get_embedding_engine

    engine = get_embedding_engine()
    for i in range(_SMALL):
        text = f"ledger entry number {i} about the zq harbour"
        store.insert_memory(
            {
                "content": text,
                "embedding": engine.encode(text),
                "domain": _DOMAIN,
                "source": "lesson",
                "heat": 0.5,
            }
        )
    monkeypatch.setattr(recall, "_store", store)
    monkeypatch.setattr(unified_search, "is_enabled", lambda: False)
    resp = asyncio.new_event_loop().run_until_complete(
        unified_search.handler(
            {
                "query": "zq harbour ledger",
                "max_results": _UNIFIED_MAX,
                "domain": _DOMAIN,
            }
        )
    )
    assert "error" not in resp
    assert resp["counts"]["cortex"] > 0
