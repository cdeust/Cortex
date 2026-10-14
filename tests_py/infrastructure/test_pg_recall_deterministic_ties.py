"""Recall cuts exact ties the same way whatever the heap layout.

Every pool of ``recall_memories()`` (vec, fts, ngram, hot, recency) ends in
``LIMIT v_pool`` and the function ends in ``LIMIT p_max_results * 3``. On
origin/main 6cecb7c2 none of these ORDER BYs was total: when more rows than
the LIMIT shared a score, the survivors followed the order the scan read the
heap, which CLUSTER, VACUUM and free-space reuse change (LongMemEval
f4f1d8a4: 110 rows at effective_heat 0.05, 10 dropped at random from
``hot``). Here 130 rows tie on one pool's score; the table is rewritten in
three physical orders and every layout must return the same rows in the
same order: newest first, ``created_at DESC, id DESC`` (ADR-1106).

Live PG (throwaway test database via conftest); skipped on SQLite.

source: ADR-1106
"""

from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone

import pytest

from tests_py.conftest import _USE_PG

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.skipif(not _USE_PG, reason="requires isolated PostgreSQL")

# source: recall_memories() v_pool = p_max_results * 10 -> 100 for
# max_results 10; 130 tied rows put 30 of them past the pool's LIMIT.
_ROWS = 130
# source: recall() default top_k (pg_recall.py), as the benchmarks call it.
_MAX_RESULTS = 10
# source: test fixture -- 13 distinct created_at values, 10 rows each, so
# both keys of the tie-break (created_at, then id) decide some position.
_STAMPS = 13
# source: pg_schema.py memories.embedding vector(384)
_DIM = 384
_DOMAIN = "ties"
_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)
# Physical orders: as inserted, pseudo-random, reversed.
_LAYOUTS = ("inserted", "md5", "reversed")
_CLUSTER_KEYS = {"md5": "(md5(id::text))", "reversed": "((-id))"}


def _axis(i: int) -> str:
    return str([1.0 if j == i else 0.0 for j in range(_DIM)])


# pool -> (row content, query text, weights); every row ties on that pool.
_POOLS = {
    "vec": ("zq vec row", "wxyv", {"p_w_vector": 1.0}),
    "fts": ("ledger entry", "ledger", {"p_w_fts": 1.0}),
    "ngram": ("ledger entry", "ledger entry", {"p_w_ngram": 1.0}),
    "hot": ("zq hot row", "wxyv", {"p_w_heat": 1.0}),
    "recency": ("zq recency row", "wxyv", {"p_w_recency": 1.0}),
}
_ZERO = {
    "p_w_vector": 0.0,
    "p_w_fts": 0.0,
    "p_w_ngram": 0.0,
    "p_w_heat": 0.0,
    "p_w_recency": 0.0,
}


@pytest.fixture
def conn():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c:
        c.execute("TRUNCATE memories CASCADE")
        yield c
        c.execute("TRUNCATE memories CASCADE")


def _stamps() -> list[datetime]:
    """created_at per insertion, shuffled so id order is not time order."""
    order = list(range(_ROWS))
    random.Random(1106).shuffle(order)
    return [_BASE - timedelta(hours=k % _STAMPS) for k in order]


def insert_tied(conn, content: str) -> list[tuple[datetime, int]]:
    """Insert the tied rows; return (created_at, id) per row."""
    keys = []
    for stamp in _stamps():
        row = conn.execute(
            "INSERT INTO memories (content, embedding, domain, source, heat_base,"
            " no_decay, created_at, heat_base_set_at, last_accessed)"
            " VALUES (%s, %s::vector, %s, 'lesson', 0.5, TRUE, %s, %s, %s)"
            " RETURNING id",
            (content, _axis(3), _DOMAIN, stamp, stamp, stamp),
        ).fetchone()
        keys.append((stamp, row[0]))
    return keys


def newest_first(keys: list[tuple[datetime, int]]) -> list[int]:
    return [i for _, i in sorted(keys, reverse=True)]


def relayout(conn, layout: str) -> None:
    """Rewrite the heap (and rebuild its indexes) in ``layout`` order."""
    if layout != "inserted":
        conn.execute(f"CREATE INDEX ties_layout ON memories {_CLUSTER_KEYS[layout]}")
        conn.execute("CLUSTER memories USING ties_layout")
        conn.execute("DROP INDEX ties_layout")
    conn.execute("VACUUM ANALYZE memories")


def recall_ids(conn, query: str, weights: dict[str, float]) -> list[int]:
    rows = conn.execute(
        "SELECT memory_id FROM recall_memories("
        " p_query_text => %s, p_query_emb => %s::vector, p_domain => %s,"
        " p_include_globals => FALSE, p_max_results => %s,"
        " p_w_vector => %s::real, p_w_fts => %s::real, p_w_heat => %s::real,"
        " p_w_ngram => %s::real, p_w_recency => %s::real)",
        (
            query,
            _axis(3),
            _DOMAIN,
            _MAX_RESULTS,
            weights["p_w_vector"],
            weights["p_w_fts"],
            weights["p_w_heat"],
            weights["p_w_ngram"],
            weights["p_w_recency"],
        ),
    ).fetchall()
    return [r[0] for r in rows]


def assert_same_in_every_layout(got: dict[str, list[int]]) -> None:
    """Same rows, same order, in every layout (the set first, then order)."""
    sets = {layout: sorted(ids) for layout, ids in got.items()}
    assert sets["md5"] == sets["inserted"] and sets["reversed"] == sets["inserted"]
    assert got["md5"] == got["inserted"] and got["reversed"] == got["inserted"]


@pytest.mark.parametrize("pool", sorted(_POOLS))
def test_recall_cuts_ties_newest_first_in_every_layout(conn, pool):
    content, query, weights = _POOLS[pool]
    expected = newest_first(insert_tied(conn, content))[: _MAX_RESULTS * 3]
    got = {}
    for layout in _LAYOUTS:
        relayout(conn, layout)
        got[layout] = recall_ids(conn, query, _ZERO | weights)
    assert_same_in_every_layout(got)
    assert got["inserted"] == expected


def test_spread_activation_cuts_ties_newest_first_in_every_layout(conn):
    conn.execute(
        "INSERT INTO entities (name, type, heat) VALUES ('zebrafish', 'concept', 1.0)"
    )
    expected = newest_first(insert_tied(conn, "zebrafish note"))[:50]
    got = {}
    for layout in _LAYOUTS:
        relayout(conn, layout)
        rows = conn.execute(
            "SELECT memory_id FROM spread_activation_memories("
            " ARRAY['zebrafish'], p_max_results => 50, p_domain => %s)",
            (_DOMAIN,),
        ).fetchall()
        got[layout] = [r[0] for r in rows]
    assert_same_in_every_layout(got)
    assert got["inserted"] == expected
