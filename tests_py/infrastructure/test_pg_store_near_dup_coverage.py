"""pg_store_near_dup.list_candidate_pairs covers every live anchor.

On origin/main the anchors were ``... LIMIT anchor_limit`` with no ORDER BY:
on a store with more live rows than the limit, each pass scanned an arbitrary
subset (the owner's store, 66,490 live rows: 271,726 and 248,965 pairs on two
runs over the same data). The scan now reads every anchor in id order, one
batch per query, and merges the batches' pairs. Live PG (throwaway test
database via conftest); skipped on SQLite.

source: ADR-0557
"""

from __future__ import annotations

import uuid

import pytest

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store
from mcp_server.infrastructure.pg_store_near_dup import list_candidate_pairs
from tests_py._pg_hnsw import empty_memories_index

# source: ADR-1112 (tests of the store itself run on the in-process store)
pytestmark = pytest.mark.in_process_store

_DIM = 384  # source: memory_config EMBEDDING_DIM (all-MiniLM-L6-v2)
# source: ADR-0557 — more live rows than one batch, so the pair, inserted
# last, lies outside the first batch (on main: outside the anchor subset).
_FILLERS = 5
_BATCH = 2  # source: same — two fillers per batch, the pair in the last one


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
    cur.execute(
        "INSERT INTO memories (content, embedding, tags, source, heat_base, no_decay)"
        " VALUES (%s, %s::vector, '[]'::jsonb, 'test', 0.5, TRUE) RETURNING id",
        (f"near-dup coverage {uuid.uuid4().hex}", vector),
    )
    return cur.fetchone()["id"]


def _fillers_then_a_pair(conn) -> tuple[int, int]:
    """Orthogonal fillers first (no pair among them), then two identical rows."""
    empty_memories_index(conn)
    with conn.cursor() as cur:
        for axis in range(_FILLERS):
            _insert(cur, _vector(10 + axis))
        return _insert(cur, _vector(300)), _insert(cur, _vector(300))


def _pair_set(conn, batch_size: int) -> set[tuple[int, int]]:
    pairs = list_candidate_pairs(
        conn, top_k=10, min_similarity=0.75, batch_size=batch_size
    )
    return {(p.id_a, p.id_b) for p in pairs}


def test_a_pair_outside_the_first_batch_is_found_on_every_run():
    store = _store()
    with store.batch_pool.connection() as conn:
        first, second = _fillers_then_a_pair(conn)
        runs = [_pair_set(conn, _BATCH) for _ in range(3)]
    assert all(run == {(first, second)} for run in runs), runs


def test_the_pair_set_does_not_depend_on_the_batch_size():
    """Two runs, and every batch size, return the identical pair set."""
    store = _store()
    with store.batch_pool.connection() as conn:
        first, second = _fillers_then_a_pair(conn)
        sets = [_pair_set(conn, size) for size in (1, _BATCH, 3, 1000, _BATCH)]
    assert all(found == {(first, second)} for found in sets), sets


def test_a_batch_size_below_one_is_refused():
    store = _store()
    with store.batch_pool.connection() as conn:
        with pytest.raises(ValueError, match="batch_size must be >= 1"):
            list_candidate_pairs(conn, batch_size=0)
