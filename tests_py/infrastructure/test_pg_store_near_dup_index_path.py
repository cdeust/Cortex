"""pg_store_near_dup.list_candidate_pairs on the HNSW index path.

Two causes, measured 2026-10-14 with pgvector 0.8.2:
- production: ``current_memories`` filters ``superseded_by_id`` (and the scan
  ``NOT is_stale``) after the HNSW top-K. Superseded rows nearer the pair
  than its members are to each other filled the ef_search candidates, so the
  duplicate was never paired. Fixed in the scan (``hnsw.iterative_scan``).
- tests: the between-test purge DELETEs rows, which stay in the index; after
  3000 identical deleted unit vectors and ANALYZE, new rows with that vector
  were unreachable in the graph (0 neighbours, iterative scan or not). This
  is what made test_near_dup_calibration_pass.py fail in long local runs
  (collapse_onto_hottest_member, transitive_component_of_three). Fixed by
  that file's precondition (tests_py/_pg_hnsw.py).
``enable_seqscan = off`` forces the index path whatever the table stats.
Live PG (throwaway test database via conftest); skipped on SQLite.

source: ADR-0557
"""

from __future__ import annotations

import math
import random
import uuid

import pytest

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store
from mcp_server.infrastructure.pg_store_near_dup import list_candidate_pairs
from tests_py._pg_hnsw import empty_memories_index

_DIM = 384  # source: memory_config EMBEDDING_DIM (all-MiniLM-L6-v2)
# source: measured 2026-10-14 (pgvector 0.8.2, default hnsw.ef_search 40):
# 300 superseded rows around the pair hid it on main; identical deleted rows
# hid new ones only at 3000 (200 did not).
_SUPERSEDED_ROWS = 300
_DELETED_ROWS = 3000


def _store():
    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    if not hasattr(store, "batch_pool"):
        pytest.skip("list_candidate_pairs is PostgreSQL-only")
    return store


def _vector(axis: int) -> str:
    values = ["0"] * _DIM
    values[axis] = "1"
    return "[" + ",".join(values) + "]"


def _insert(cur, vector: str) -> int:
    return _insert_many(cur, [vector])[0]


def _insert_many(cur, vectors: list[str]) -> list[int]:
    """One round trip for many rows (psycopg executemany with RETURNING)."""
    cur.executemany(
        "INSERT INTO memories (content, embedding, tags, source, heat_base, no_decay)"
        " VALUES (%s, %s::vector, '[]'::jsonb, 'test', 0.5, TRUE) RETURNING id",
        [(f"near-dup index path {uuid.uuid4().hex}", v) for v in vectors],
        returning=True,
    )
    ids = []
    while True:
        ids.append(cur.fetchone()["id"])
        if not cur.nextset():
            return ids


def _pairs_on_the_index_path(conn) -> list:
    conn.execute("ANALYZE memories")
    conn.execute("SET enable_seqscan = off")
    try:
        return list_candidate_pairs(conn, top_k=10, min_similarity=0.75)
    finally:
        conn.execute("RESET enable_seqscan")


def _unit(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    return [v / norm for v in values]


def _jitter(center: list[float], noise: float, rng: random.Random) -> list[float]:
    """A distinct unit vector near ``center`` (cosine ~1 - noise^2/2)."""
    return _unit([c + rng.gauss(0.0, noise / math.sqrt(_DIM)) for c in center])


def _literal(values: list[float]) -> str:
    return "[" + ",".join(repr(v) for v in values) + "]"


def test_a_duplicate_behind_superseded_rows_is_paired():
    """The production case: current_memories filters superseded_by_id after
    the HNSW scan. Superseded rows around the midpoint are nearer to each
    member of the live pair than the members are to each other, so from
    either anchor the ef_search candidates were all filtered out."""
    store = _store()
    rng = random.Random(1104)  # source: fixed seed, deterministic vectors
    first = _unit([1.0 if i == 120 else 0.0 for i in range(_DIM)])
    second = _unit(
        [1.0 if i == 120 else 0.33 if i == 121 else 0.0 for i in range(_DIM)]
    )
    middle = _unit([a + b for a, b in zip(first, second, strict=True)])
    with store.batch_pool.connection() as conn:
        empty_memories_index(conn)
        with conn.cursor() as cur:
            survivor = _insert(cur, _vector(200))
            hidden = _insert_many(
                cur,
                [_literal(_jitter(middle, 0.05, rng)) for _ in range(_SUPERSEDED_ROWS)],
            )
            cur.execute(
                "UPDATE memories SET superseded_by_id = %s WHERE id = ANY(%s)",
                (survivor, hidden),
            )
            first_id = _insert(cur, _literal(first))
            second_id = _insert(cur, _literal(second))
        pairs = _pairs_on_the_index_path(conn)
    assert any({p.id_a, p.id_b} == {first_id, second_id} for p in pairs), pairs


def test_an_emptied_index_no_longer_hides_new_rows():
    """The test precondition (tests_py/_pg_hnsw.py): rows deleted by earlier
    tests stay in the index; emptying it makes the near-dup tests independent
    of what ran before them."""
    store = _store()
    vector = _vector(122)
    with store.batch_pool.connection() as conn:
        with conn.cursor() as cur:
            earlier = _insert_many(cur, [vector] * _DELETED_ROWS)
            cur.execute("DELETE FROM memories WHERE id = ANY(%s)", (earlier,))
        empty_memories_index(conn)
        with conn.cursor() as cur:
            first, second = _insert(cur, vector), _insert(cur, vector)
        pairs = _pairs_on_the_index_path(conn)
    assert any({p.id_a, p.id_b} == {first, second} for p in pairs), pairs
