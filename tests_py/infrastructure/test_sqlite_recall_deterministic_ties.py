"""SQLite recall orders exact ties like PostgreSQL: newest first.

The SQLite fusion is rank-based (RRF): a row's score is ``w / (k + rank)``,
so the order of tied rows inside a signal decides their scores, not only
which rows a LIMIT keeps. On origin/main 6cecb7c2 the heat and recency
signals ordered ties by whatever index or table order SQLite read, and the
final sort kept the dict's insertion order. ADR-1106 makes every signal and
the final sort break exact ties by ``created_at DESC, id DESC``, the same key
as ``recall_memories()`` on PostgreSQL.

source: ADR-1106
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from tests_py._sqlite_vec import require_sqlite_vec

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

# source: SqliteSearchMixin.recall_memories pool = max_results * 10 -> 100;
# 130 tied rows put 30 of them past each signal's LIMIT.
_ROWS = 130
# source: recall() default top_k (pg_recall.py), as the benchmarks call it.
_MAX_RESULTS = 10
# source: test fixture -- 13 created_at values, so both tie-break keys act.
_STAMPS = 13
# source: sqlite_schema.py memories_vec embedding float[384]
_DIM = 384
_DOMAIN = "sqlite-ties"
_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
_ZERO = {"vector": 0.0, "fts": 0.0, "heat": 0.0, "recency": 0.0}


@pytest.fixture
def store():
    s = SqliteMemoryStore()
    yield s
    s.close()


def _axis() -> bytes:
    v = np.zeros(_DIM, dtype=np.float32)
    v[3] = 1.0
    return v.tobytes()


def insert_tied(store: SqliteMemoryStore, content: str) -> list[int]:
    """Insert tied rows with shuffled created_at; return ids newest first."""
    order = list(range(_ROWS))
    random.Random(1106).shuffle(order)
    keys = []
    for k in order:
        stamp = (_BASE - timedelta(hours=k % _STAMPS)).isoformat()
        mid = store.insert_memory(
            {
                "content": content,
                "embedding": _axis(),
                "domain": _DOMAIN,
                "source": "lesson",
                "heat": 0.5,
                "created_at": stamp,
            }
        )
        keys.append((stamp, mid))
    return [i for _, i in sorted(keys, reverse=True)]


@pytest.mark.parametrize(
    ("signal", "content", "query"),
    [
        ("heat", "zq heat row", "wxyv"),
        ("recency", "zq recency row", "wxyv"),
        ("fts", "ledger entry", "ledger"),
    ],
)
def test_sqlite_recall_cuts_ties_newest_first(store, signal, content, query):
    newest = insert_tied(store, content)
    # Every tied row gets the same credit (ADR-1109), so the final sort's
    # created_at DESC, id DESC decides the order, for every signal.
    expected = newest[: _MAX_RESULTS * 3]
    rows = store.recall_memories(
        query_text=query,
        query_embedding=None,
        domain=_DOMAIN,
        min_heat=0.0,
        max_results=_MAX_RESULTS,
        weights=_ZERO | {signal: 1.0},
    )
    assert [r["memory_id"] for r in rows] == expected


def test_sqlite_vector_ties_are_ranked_newest_first(store):
    """vec0's KNN takes no second ORDER BY key: the order of the rows it
    returns is total (newest first); which rows it keeps at its own LIMIT is
    vec0's choice, so this case stays under the pool size."""
    require_sqlite_vec()
    newest = insert_tied(store, "zq vec row")
    rows = store.recall_memories(
        query_text="wxyv",
        query_embedding=_axis(),
        domain=_DOMAIN,
        min_heat=0.0,
        max_results=_ROWS,
        weights=_ZERO | {"vector": 1.0},
    )
    assert [r["memory_id"] for r in rows] == newest
