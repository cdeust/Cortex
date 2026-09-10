"""Pure infrastructure — no core imports, no handler imports.

source: ADR-0557"""

from __future__ import annotations

from mcp_server.infrastructure.row_factory import DICT_ROW

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection


from mcp_server.shared.near_dup_calibration import SCAN_FLOOR, CandidatePair

# source: ADR-0557
DEFAULT_TOP_K = 30

# source: ADR-0557
DEFAULT_ANCHOR_LIMIT = 20000


def list_candidate_pairs(
    conn: StoreConnection,
    *,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = SCAN_FLOOR,
    anchor_limit: int = DEFAULT_ANCHOR_LIMIT,
) -> list[CandidatePair]:
    """Find undirected candidate pairs using per-row top-K vector scans.

    Pre-condition: top_k >= 1 and min_similarity is in [0, 1].

    Post-condition: return distinct CandidatePair entries with id_a < id_b and
    cosine similarity >= min_similarity, discovered from either member’s scan.
    Both members are non-stale chain heads with embeddings. Exclude self-pairs
    and order by (id_a, id_b).

    source: ADR-0557"""
    sql = """
        WITH anchors AS (
            SELECT id, embedding
              FROM current_memories
             WHERE NOT is_stale AND embedding IS NOT NULL
             LIMIT %(anchor_limit)s
        )
        SELECT DISTINCT
               LEAST(a.id, nn.id)    AS id_a,
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
         ORDER BY 1, 2
    """
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(
            sql,
            {
                "anchor_limit": anchor_limit,
                "top_k": top_k,
                "min_similarity": min_similarity,
            },
        )
        rows = cur.fetchall()
    return [
        CandidatePair(id_a=row["id_a"], id_b=row["id_b"], similarity=row["similarity"])
        for row in rows
    ]


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
    "DEFAULT_ANCHOR_LIMIT",
    "DEFAULT_TOP_K",
    "list_candidate_pairs",
    "fetch_contents",
    "fetch_member_stats",
]
