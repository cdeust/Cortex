"""Start a PostgreSQL test from an empty ``memories`` HNSW index.

The between-test purge (``_store_cleanup._clean_all_tables``) DELETEs rows;
their index entries stay until a vacuum. Tests that assert on what an HNSW
top-K returns (the near-dup scan) then depend on every earlier test: identical
unit vectors from earlier near-dup tests grow a graph from which new rows
cannot be reached, and the scan returns nothing (measured 2026-10-14 with
pgvector 0.8.2: 3000 deleted identical rows, ANALYZE, then 0 neighbours, with
or without hnsw.iterative_scan). TRUNCATE for the whole suite cost 66 s ->
466 s on tests_py/handlers, so only these tests pay for it.

source: ADR-0557
"""

from __future__ import annotations


def empty_memories_index(conn) -> None:
    """TRUNCATE ``memories`` and the tables that reference it."""
    conn.execute("TRUNCATE memories CASCADE")
