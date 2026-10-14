"""Every HNSW scan on a Cortex connection reads past ``hnsw.ef_search``.

pgvector's HNSW index hands the executor at most ``hnsw.ef_search`` (40 by
default) candidates; WHERE filters, and the ``current_memories`` view's
``superseded_by_id IS NULL``, are applied only after that. A vector top-K
followed by filters therefore silently missed relevant rows behind filtered
neighbours, and a LIMIT above ef_search could not be reached through the
index at all. With ``hnsw.iterative_scan`` the scan keeps reading the index
until the LIMIT is filled or ``hnsw.max_scan_tuples`` index tuples are seen.

The setting is a session setting, applied to every connection the store
opens (pool ``configure`` callback, the persistent connection, reconnects),
so it covers the PL/pgSQL ``recall_memories()`` and every Python ANN query.

source: ADR-1105 (pgvector README, "Iterative Index Scans", 0.8.0+)"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp_server.infrastructure.row_factory import DICT_ROW

if TYPE_CHECKING:
    from psycopg import Connection

# source: pgvector README, "Iterative Index Scans": relaxed_order "provides
# better recall" but rows come "slightly out of order", fixed by re-sorting
# outside a materialized CTE. Measured 2026-10-14, read-only on the live store
# (68,496 rows, 100 queries, ADR-1105): vec-pool recall against an exact scan
# 0.578 off, 0.919 strict_order, 0.939 relaxed_order; recall_memories() top-10
# identical to the exact one in 51, 72 and 81 of 100. The PL/pgSQL fusion is
# score-based (order-free); the Python ANN queries re-sort.
_ENABLE_ITERATIVE_SCAN = "SET hnsw.iterative_scan = relaxed_order"
# source: PostgreSQL docs, current_setting(name, missing_ok): NULL when the
# parameter does not exist. Loading vector.so (any vector value) defines the
# hnsw.* parameters, so the question is answered by the library in use.
_LOAD_VECTOR = "SELECT '[1]'::vector"
_ITERATIVE_SCAN_SETTING = (
    "SELECT current_setting('hnsw.iterative_scan', true) AS setting"
)
MISSING_ITERATIVE_SCAN = (
    "Cortex needs hnsw.iterative_scan (pgvector >= 0.8.0); the pgvector "
    "library loaded by this PostgreSQL server does not define it. Upgrade "
    "pgvector (https://github.com/pgvector/pgvector#installation)."
)


def require_iterative_scan(cur: Any) -> None:
    """Refuse a pgvector that cannot scan iteratively (before 0.8.0).

    Pre-condition: ``cur`` yields dict rows.
    Post-condition: returns only when the loaded library defines
    ``hnsw.iterative_scan``; raises RuntimeError otherwise.

    PostgreSQL accepts a SET of an unknown ``hnsw.*`` name on a backend that
    has not loaded the extension yet and, on a library without the
    parameter, drops it with a server WARNING only (measured in review of
    #754): every vector query would stay lossy without a word. The loaded
    library decides, not the catalogue's extversion, which can lag an
    upgraded binary."""
    cur.execute(_LOAD_VECTOR)
    cur.execute(_ITERATIVE_SCAN_SETTING)
    row = cur.fetchone()
    if row is None or row["setting"] is None:
        raise RuntimeError(MISSING_ITERATIVE_SCAN)


def enable_iterative_scan(conn: Connection[Any]) -> None:
    """Turn the iterative scan on for the rest of ``conn``'s session.

    Pre-condition: ``conn`` is idle (autocommit), so a plain SET outlives
    the statement; the ``vector`` extension exists in its database.
    Post-condition: ``SHOW hnsw.iterative_scan`` is ``relaxed_order``."""
    with conn.cursor(row_factory=DICT_ROW) as cur:
        require_iterative_scan(cur)
        cur.execute(_ENABLE_ITERATIVE_SCAN)
