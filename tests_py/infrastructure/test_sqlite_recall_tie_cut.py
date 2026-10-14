"""SQLite recall: a signal's cut and its rank credit ignore tie-breaks.

The SQLite fusion is rank-based: a row's credit is ``w / (k + rank)``. On
origin/main b2e63876 (ADR-1106) the rows of a tie group got distinct ranks
by ``created_at DESC, id DESC`` (heat: ``id DESC``) and the pool's LIMIT kept
the newest: within one tie, the newest row got ``w / (k + 1)`` and the
oldest nothing. ADR-1109 keeps the whole boundary tie group and gives each
tied row the mean credit of the positions the group occupies.

Here 130 rows tie on one signal and the answer, the oldest or the newest of
them, also carries a second signal the others lack. The answer must rank
first, alone, and its score must be the tie's mean credit plus the second
signal's rank-1 credit, whatever its age. Both cases fail on origin/main:
the oldest answer loses the tied signal, the newest gets rank 1's credit
instead of the group's.

source: ADR-1109
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

# source: SqliteSearchMixin.recall_memories pool = max_results * 10 -> 100;
# 130 tied rows put 30 of them past each signal's cut.
_ROWS = 130
# source: recall() default top_k (pg_recall.py), as the benchmarks call it.
_MAX_RESULTS = 10
# source: SqliteSearchMixin.recall_memories wrrf_k default
_K = 60
# source: sqlite_schema.py memories_vec embedding float[384]
_DIM = 384
_DOMAIN = "sqlite-tie-cut"
_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
# source: test fixture -- the tied heat, and the answer's when heat is the
# second signal.
_HEAT, _ANSWER_HEAT = 0.5, 0.9

# tied signal -> (content, answer content, query, second signal)
_CASES = {
    "heat": ("zq row", "zq ledger row", "ledger", "fts"),
    "fts": ("ledger entry", "ledger entry", "ledger", "heat"),
    "recency": ("zq row", "zq ledger row", "ledger", "fts"),
    "vector": ("zq row", "zq row", "wxyv", "heat"),
}


@pytest.fixture
def store():
    s = SqliteMemoryStore()
    yield s
    s.close()


def _axis() -> bytes:
    v = np.zeros(_DIM, dtype=np.float32)
    v[3] = 1.0
    return v.tobytes()


def insert_case(store: SqliteMemoryStore, signal: str, answer_end: str) -> int:
    """130 rows tied on ``signal``, inserted oldest first; return the answer."""
    content, answer_content, _, second = _CASES[signal]
    answer_at = 0 if answer_end == "oldest" else _ROWS - 1
    answer = 0
    for i in range(_ROWS):
        stamp = _BASE if signal == "recency" else _BASE + timedelta(hours=i)
        is_answer = i == answer_at
        mid = store.insert_memory(
            {
                "content": answer_content if is_answer else content,
                "embedding": _axis(),
                "domain": _DOMAIN,
                "source": "lesson",
                "heat": _ANSWER_HEAT if is_answer and second == "heat" else _HEAT,
                "created_at": stamp.isoformat(),
            }
        )
        answer = mid if is_answer else answer
    return answer


def group_credit(first: int, last: int) -> float:
    """Mean of 1 / (k + r) over positions first..last."""
    return sum(1.0 / (_K + r) for r in range(first, last + 1)) / (last - first + 1)


@pytest.mark.parametrize("answer_end", ["oldest", "newest"])
@pytest.mark.parametrize("signal", sorted(_CASES))
def test_answer_gets_the_tie_groups_credit_whatever_its_age(store, signal, answer_end):
    if signal == "vector" and not store._has_vec:
        pytest.fail("sqlite-vec must be loaded for the vector case")
    answer = insert_case(store, signal, answer_end)
    _, _, query, second = _CASES[signal]
    rows = store.recall_memories(
        query_text=query,
        query_embedding=_axis() if signal == "vector" else None,
        domain=_DOMAIN,
        min_heat=0.0,
        max_results=_MAX_RESULTS,
        weights={"vector": 0.0, "fts": 0.0, "heat": 0.0, "recency": 0.0}
        | {signal: 1.0, second: 1.0},
    )
    assert rows[0]["memory_id"] == answer
    assert rows[0]["score"] > rows[1]["score"]
    expected = group_credit(1, _ROWS) + group_credit(1, 1)
    assert rows[0]["score"] == pytest.approx(expected, rel=1e-12)
