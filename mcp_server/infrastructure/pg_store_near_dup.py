"""Pure infrastructure — no core imports, no handler imports.

source: ADR-0557"""

from __future__ import annotations

from mcp_server.infrastructure.pg_iterative_scan import require_iterative_scan
from mcp_server.infrastructure.row_factory import DICT_ROW

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from psycopg import Connection
    from psycopg.rows import DictRow

    from mcp_server.infrastructure.db_types import StoreConnection


from mcp_server.shared.near_dup_calibration import (
    SCAN_FLOOR,
    CandidatePair,
    merge_pair_batches,
)
from mcp_server.infrastructure.store_operations import store_operation

# source: ADR-0557
DEFAULT_TOP_K = 30

# Anchors per query (each batch is one transaction), not a coverage limit.
# source: measured 2026-10-14 on a restored copy of the owner's store (66,547
# live memories, pgvector 0.8.2, top_k 30, Apple M4, load average ~6): one
# batch of 5000 takes 4.8 s and returns 95,505 rows (1000: 1.1 s; 20000:
# 27.8 s); batch sizes 1000, 5000 and 20000 give the same 686,268 pairs.
DEFAULT_ANCHOR_BATCH = 5000


# source: pgvector README, "Iterative Index Scans" (0.8.0+): strict_order
# keeps exact distance order, which the per-anchor ORDER BY ... LIMIT needs.
# The store's connections scan iteratively for the whole session with
# relaxed_order (ADR-1105); this scan keeps strict_order in its transaction.
_ITERATIVE_SCAN = "SET LOCAL hnsw.iterative_scan = strict_order"


# source: PostgreSQL docs, "Numeric Types": memories.id is SERIAL (integer,
# pg_schema.py), whose range starts at -2147483648; every id is above this.
_BEFORE_FIRST_ID = -2147483649

_LAST_ANCHOR_SQL = """
    SELECT MAX(id) AS last_id
      FROM (SELECT id
              FROM current_memories
             WHERE NOT is_stale AND embedding IS NOT NULL
               AND id > %(after_id)s
             ORDER BY id
             LIMIT %(batch_size)s) batch
"""

# The anchors are one id range; the LATERAL neighbours range over every live
# row, so a pair is found from whichever member's batch reaches it.
_BATCH_PAIRS_SQL = """
    WITH anchors AS (
        SELECT id, embedding
          FROM current_memories
         WHERE NOT is_stale AND embedding IS NOT NULL
           AND id > %(after_id)s AND id <= %(last_id)s
    )
    SELECT LEAST(a.id, nn.id)    AS id_a,
           GREATEST(a.id, nn.id) AS id_b,
           MAX(1 - (a.embedding <=> nn.embedding))::REAL AS similarity
      FROM anchors a
      JOIN LATERAL (
            SELECT b.id, b.embedding
              FROM current_memories b
             WHERE NOT b.is_stale
               AND b.embedding IS NOT NULL
               AND b.id <> a.id
             ORDER BY a.embedding <=> b.embedding
             LIMIT %(top_k)s
           ) nn ON TRUE
     WHERE (1 - (a.embedding <=> nn.embedding)) >= %(min_similarity)s
     GROUP BY 1, 2
"""


def _scan_anchor_batch(
    conn: Connection[DictRow], params: dict
) -> tuple[int | None, list[CandidatePair]]:
    """Scan the next ``batch_size`` anchors after ``after_id``, by id.

    Post-condition: (last anchor id, pairs), or (None, []) when no live
    anchor follows ``after_id``. One transaction per batch: the iterative
    scan setting is transaction-local.

    The LATERAL top-K uses the HNSW index, which yields at most
    hnsw.ef_search candidates before the view's superseded_by_id filter,
    NOT is_stale and dead tuples are applied; a duplicate behind those rows
    was never paired. An iterative scan keeps reading the index, in exact
    distance order, until top_k rows pass (bounded by hnsw.max_scan_tuples)."""
    with conn.transaction(), conn.cursor(row_factory=DICT_ROW) as cur:
        require_iterative_scan(cur)
        cur.execute(_ITERATIVE_SCAN)
        cur.execute(_LAST_ANCHOR_SQL, params)
        row = cur.fetchone()
        last_id = None if row is None else row["last_id"]
        if last_id is None:
            return None, []
        cur.execute(_BATCH_PAIRS_SQL, {**params, "last_id": last_id})
        rows = cur.fetchall()
    return last_id, [
        CandidatePair(id_a=r["id_a"], id_b=r["id_b"], similarity=r["similarity"])
        for r in rows
    ]


def _anchor_batches(
    conn: Connection[DictRow], params: dict
) -> Iterator[list[CandidatePair]]:
    """Yield each batch's pairs, keyset-paginated by id until none is left."""
    after_id = _BEFORE_FIRST_ID
    while True:
        last_id, pairs = _scan_anchor_batch(conn, {**params, "after_id": after_id})
        if last_id is None:
            return
        yield pairs
        after_id = last_id


@store_operation
def list_candidate_pairs(
    conn: Connection[DictRow],
    *,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = SCAN_FLOOR,
    batch_size: int = DEFAULT_ANCHOR_BATCH,
) -> list[CandidatePair]:
    """Find undirected candidate pairs using per-row top-K vector scans.

    Every live row is an anchor: the anchors are read in id order,
    ``batch_size`` per query, each batch in its own transaction, and the
    batches' pairs are merged. The result does not depend on the batch size
    or on the heap order.

    Pre-condition: top_k >= 1, batch_size >= 1 and min_similarity is in
    [0, 1]; ``conn`` is a PostgreSQL connection (pgvector >= 0.8.0:
    ``hnsw.iterative_scan``).

    Post-condition: return distinct CandidatePair entries with id_a < id_b and
    cosine similarity >= min_similarity, discovered from either member’s scan.
    Both members are non-stale chain heads with embeddings. Exclude self-pairs
    and order by (id_a, id_b).

    source: ADR-0557"""
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")
    params = {
        "batch_size": batch_size,
        "top_k": top_k,
        "min_similarity": min_similarity,
    }
    return merge_pair_batches(_anchor_batches(conn, params))


# Same expression and REAL cast as _BATCH_PAIRS_SQL's similarity, so a pair
# the scan put at or above the threshold passes this test too.
_NEAR_TO_SQL = """
    SELECT m.id
      FROM current_memories s
      JOIN current_memories m ON m.id = ANY(%(ids)s)
     WHERE s.id = %(anchor_id)s
       AND NOT s.is_stale AND s.embedding IS NOT NULL
       AND NOT m.is_stale AND m.embedding IS NOT NULL
       AND (1 - (s.embedding <=> m.embedding))::REAL >= %(threshold)s
"""


@store_operation
def ids_near_to(
    conn: StoreConnection, anchor_id: int, ids: list[int], *, threshold: float
) -> set[int]:
    """Ids of ``ids`` whose own cosine similarity to ``anchor_id`` is at or
    above ``threshold``, computed from the two embeddings.

    Post-condition: a subset of ``ids``; both rows are non-stale chain heads
    with embeddings (a row superseded since the scan is absent, and so is
    every id when the anchor itself is). Does not read the candidate pairs:
    a near-duplicate the top-K scan never paired with the anchor is found.

    source: ADR-0557"""
    if not ids:
        return set()
    params = {"anchor_id": anchor_id, "ids": ids, "threshold": threshold}
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(_NEAR_TO_SQL, params)
        return {row["id"] for row in cur.fetchall()}


@store_operation
def fetch_contents(conn: StoreConnection, ids: list[int]) -> dict[int, str]:
    """Fetch content text for the supplied memory IDs.

    Post-condition: return {id: content} for IDs still present in
    current_memories. Missing or superseded IDs are omitted; callers must
    handle absent keys.

    source: ADR-0557"""
    if not ids:
        return {}
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(
            "SELECT id, content FROM current_memories WHERE id = ANY(%(ids)s)",
            {"ids": ids},
        )
        return {row["id"]: row["content"] for row in cur.fetchall()}


@store_operation
def fetch_member_stats(conn: StoreConnection, ids: list[int]) -> dict[int, dict]:
    """Fetch heat and creation time for the supplied current memory IDs.

    Post-condition: return {id: {effective_heat: float, created_at:
    datetime}}. Missing or superseded IDs are omitted.

    source: ADR-0557"""
    if not ids:
        return {}
    sql = """
        WITH candidates AS (
            SELECT m.*
              FROM current_memories m
             WHERE NOT m.is_stale
        )
        SELECT c.id,
               effective_heat(c, NOW(), COALESCE(hs.factor, 1.0))::REAL
                   AS effective_heat,
               c.created_at
          FROM candidates c
     -- source: ADR-0557
     LEFT JOIN homeostatic_state hs ON hs.domain = c.domain AND hs.write_class = 'auto'
         WHERE c.id = ANY(%(ids)s)
    """
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(sql, {"ids": ids})
        return {
            row["id"]: {
                "effective_heat": row["effective_heat"],
                "created_at": row["created_at"],
            }
            for row in cur.fetchall()
        }


__all__ = [
    "DEFAULT_ANCHOR_BATCH",
    "DEFAULT_TOP_K",
    "list_candidate_pairs",
    "ids_near_to",
    "fetch_contents",
    "fetch_member_stats",
]
