"""Every ANN query reaches past hnsw.ef_search on the HNSW index path.

pgvector applies WHERE filters, and ``current_memories``' superseded_by_id
filter, after the index has produced at most hnsw.ef_search (40) candidates.
Here 300 distinct rows nearer the query than the relevant row are filtered
out (superseded, stale, other domain, untagged, older); without
``hnsw.iterative_scan`` the relevant row was never returned (fails on
origin/main 759fce8f, measured 2026-10-14 with pgvector 0.8.2).

Each test builds its own store with seq scans and sorts disabled through
``PGOPTIONS``, so every connection it opens (pools, persistent connection)
takes the HNSW index path, and starts from an empty index
(tests_py/_pg_hnsw.py). Live PG (throwaway test database via conftest);
skipped on SQLite.

source: ADR-1105
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store
from tests_py._pg_ann_rows import (
    DIM,
    Row,
    hidden_near,
    insert_rows,
    relevant_row,
    unit_axis,
)
from tests_py._pg_hnsw import empty_memories_index

# source: test_pg_store_near_dup_index_path.py — 300 hidden rows exceed the
# default hnsw.ef_search (40) several times over.
_HIDDEN_ROWS = 300
# source: recall_memories() v_pool = p_max_results * 10; 30 hotter, newer
# decoys fill the heat and recency pools (10 each) for max_results=1.
_DECOYS = 30
# source: measured 2026-10-14 on 300 rows: with seq scans off alone the
# planner took a bitmap scan on idx_memories_heat_base_id plus a Sort, which
# is exact; with sorts off too, the ORDER BY distance LIMIT reads the HNSW
# index, the plan the live store (tens of thousands of rows) chooses itself.
_INDEX_PATH = "-c enable_seqscan=off -c enable_sort=off"
_MODE = "relaxed_order"  # source: ADR-1105 (pgvector README, measured recall)


@pytest.fixture
def index_store(monkeypatch):
    """A PgMemoryStore whose every connection plans without seq scans."""
    settings = get_memory_settings()
    shared = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    if not hasattr(shared, "batch_pool"):
        pytest.skip("HNSW index path is PostgreSQL-only")
    from mcp_server.infrastructure.pg_store import PgMemoryStore  # noqa: PLC0415 — PG-only import

    with shared.batch_pool.connection() as conn:
        empty_memories_index(conn)
    monkeypatch.setenv("PGOPTIONS", _INDEX_PATH)
    store = PgMemoryStore(database_url=os.environ["DATABASE_URL"])
    yield store
    store.close()


def _query() -> list[float]:
    return unit_axis(150)


def _as_bytes(vector: list[float]) -> bytes:
    return np.asarray(vector, dtype=np.float32).tobytes()


def _decoys(domain: str) -> list[Row]:
    """Hotter, newer, far from the query, matching neither FTS nor trigram."""
    return [
        Row(unit_axis(250 + i % 40), content=f"zq decoy {i}", heat=0.9, domain=domain)
        for i in range(_DECOYS)
    ]


_HIDING = {
    "superseded": {"superseded": True},
    "stale": {"is_stale": True},
    "other_domain": {"domain": "other"},
}


@pytest.mark.parametrize("kind", sorted(_HIDING))
def test_recall_memories_finds_a_row_behind_filtered_neighbours(index_store, kind):
    """The PL/pgSQL vec CTE: ORDER BY distance LIMIT v_pool over eligible."""
    hidden = hidden_near(_query(), _HIDDEN_ROWS, **{"domain": "mine", **_HIDING[kind]})
    ids = insert_rows(index_store, [relevant_row(_query(), domain="mine")])
    insert_rows(index_store, hidden + _decoys("mine"))
    rows = index_store.recall_memories(
        "wxyv",
        _as_bytes(_query()),
        domain="mine",
        max_results=1,
        include_globals=False,
        weights={"vector": 1.0, "fts": 0.0, "heat": 0.0, "ngram": 0.0},
    )
    assert ids[0] in [r["memory_id"] for r in rows], rows


def test_search_vectors_finds_a_row_behind_stale_neighbours(index_store):
    insert_rows(index_store, hidden_near(_query(), _HIDDEN_ROWS, is_stale=True))
    ids = insert_rows(index_store, [relevant_row(_query())])
    found = index_store.search_vectors(_as_bytes(_query()), top_k=1, heads_only=True)
    assert [i for i, _ in found] == ids


def test_search_by_tag_vector_finds_a_row_behind_untagged_neighbours(index_store):
    insert_rows(index_store, hidden_near(_query(), _HIDDEN_ROWS))
    ids = insert_rows(index_store, [relevant_row(_query(), tags=["wanted"])])
    found = index_store.search_by_tag_vector(_as_bytes(_query()), "wanted", limit=1)
    assert [r["id"] for r in found] == ids


def test_search_newer_neighbors_finds_a_row_behind_older_neighbours(index_store):
    insert_rows(index_store, hidden_near(_query(), _HIDDEN_ROWS, created="2020-01-01"))
    ids = insert_rows(index_store, [relevant_row(_query())])
    found = index_store.search_newer_neighbors(
        _as_bytes(_query()), after="2021-01-01", exclude_id=-1, top_k=1
    )
    assert len(found) == 1, (ids, found)
    assert found[0][0] == pytest.approx(0.8, abs=1e-4)


def _mode(conn) -> str:
    return conn.execute("SHOW hnsw.iterative_scan").fetchone()["hnsw.iterative_scan"]


def test_every_store_connection_scans_iteratively(index_store):
    """Pools (configure callback), the persistent connection, a reconnect."""
    with index_store.interactive_pool.connection() as conn:
        assert _mode(conn) == _MODE
    with index_store.batch_pool.connection() as conn:
        assert _mode(conn) == _MODE
    assert _mode(index_store._conn) == _MODE
    index_store._reconnect()
    assert _mode(index_store._conn) == _MODE


def test_python_ann_results_come_nearest_first(index_store):
    """relaxed_order may emit rows slightly out of order; the queries
    re-sort outside a materialized CTE."""
    insert_rows(index_store, hidden_near(_query(), _HIDDEN_ROWS))
    found = index_store.search_vectors(_as_bytes(_query()), top_k=50)
    distances = [d for _, d in found]
    assert len(distances) == 50 and distances == sorted(distances)


def test_the_dimension_matches_the_schema():
    assert get_memory_settings().EMBEDDING_DIM == DIM
