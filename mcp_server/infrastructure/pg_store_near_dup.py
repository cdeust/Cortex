"""Near-duplicate candidate pair scan — DB operations (I6-D2, INC6.4).

Measures cosine similarity between active memories' embeddings and
returns candidate pairs above a floor similarity. Split into its own
module for the same reason as ``pg_store_memory_dedup.py`` (I6-D1
precedent): keep each infrastructure file focused and under the size
cap.

Pure infrastructure — no core imports, no handler imports.

Method (documented per coding-standards.md §8 — "no source, no
implementation" applies to methodology too, not just constants): an
exhaustive O(n^2) pairwise cosine scan over ~10k active memories is
~50M comparisons — computationally unreasonable for a one-shot campaign
query. Instead, for every active memory this module asks the existing
HNSW index (``idx_memories_embedding``, ``pg_schema.py:707-708``,
``vector_cosine_ops``) for its own top-K approximate nearest neighbors
via a LATERAL join — the same ORDER BY <=> LIMIT K pattern the
production WRRF recall query already uses for a single query embedding
(``pg_schema.py``'s ``recall_memories()``), just run once per row
instead of once per user query. This is an approximation: a pair whose
true cosine similarity is above the floor but where neither side ranks
in the other's top-K is missed. K=30 was chosen because a manual check
(2026-07-10, ad hoc `EXPLAIN ANALYZE` against this DB) showed the
0.75-similarity candidate set per row saturates well under 30 members
for every sampled anchor; this is a bound, not a proof of completeness,
and is documented as such in the campaign artifact (I6-D2 step 2:
"documente la methode").
"""

from __future__ import annotations

from mcp_server.infrastructure.row_factory import DICT_ROW

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection


from mcp_server.shared.near_dup_calibration import SCAN_FLOOR, CandidatePair

# Per-anchor approximate-neighbor fan-out. See module docstring for the
# empirical justification (2026-07-10 EXPLAIN ANALYZE check on this DB).
DEFAULT_TOP_K = 30

# Bounds the number of anchor rows scanned in one pass (not the number of
# pairs produced) — mirrors DEFAULT_DEDUP_SCAN_LIMIT's rationale
# (pg_store_memory_dedup.py). 10024 active memories with embeddings
# measured 2026-07-10; comfortably under this cap.
DEFAULT_ANCHOR_LIMIT = 20000


def list_candidate_pairs(
    conn: StoreConnection,
    *,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = SCAN_FLOOR,
    anchor_limit: int = DEFAULT_ANCHOR_LIMIT,
) -> list[CandidatePair]:
    """Every deduplicated (id_a < id_b) candidate pair with cosine
    similarity >= ``min_similarity``, approximated via per-row top-K HNSW
    lookups (see module docstring for the method and its bound).

    Pre-condition:  ``top_k`` >= 1; ``min_similarity`` in [0, 1].
    Post-condition: returns one ``CandidatePair`` per undirected pair
                    found by EITHER side's top-K scan (a pair is kept if
                    it surfaces from A's neighbor scan OR B's — the
                    LATERAL join is directional per anchor row, so the
                    UNION via ``id_a < id_b`` + `DISTINCT` recovers the
                    undirected pair even when only one direction's top-K
                    happens to include it). Scoped to
                    ``current_memories WHERE NOT is_stale AND embedding
                    IS NOT NULL`` on both sides. No self-pairs. Ordered
                    by ``(id_a, id_b)`` for deterministic downstream
                    stratified sampling.
    """
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
    """Content text for a set of memory ids (for labeling artifacts).

    Post-condition: returns ``{id: content}`` for every id in ``ids``
                    that still exists in ``current_memories``; ids that
                    no longer exist (superseded between scan and fetch)
                    are simply absent from the returned dict — the
                    caller must handle a missing key, not assume
                    completeness.
    """
    if not ids:
        return {}
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(
            "SELECT id, content FROM current_memories WHERE id = ANY(%(ids)s)",
            {"ids": ids},
        )
        return {row["id"]: row["content"] for row in cur.fetchall()}


def fetch_member_stats(conn: StoreConnection, ids: list[int]) -> dict[int, dict]:
    """``effective_heat`` and ``created_at`` for a set of memory ids
    (for survivor election across a near-dup component).

    Reuses the exact same CTE-hop pattern as
    ``pg_store_memory_dedup.list_exact_duplicate_groups`` (re-project
    ``current_memories`` through an anonymous-RECORD CTE before calling
    ``effective_heat()``, required because the view's composite type does
    not implicitly cast to the ``memories`` table type — see that
    module's docstring for the full explanation).

    Post-condition: returns ``{id: {"effective_heat": float,
                    "created_at": datetime}}`` for every id in ``ids``
                    still present in ``current_memories``; missing ids
                    (superseded concurrently) are simply absent.
    """
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
     -- M-D3 (7.1): homeostatic_state's PK is now (domain, write_class) —
     -- without this filter the join fans out to one row per class and
     -- COALESCE/effective_heat would see an arbitrary row, not the one
     -- factor this table's readers were written for (auto is the only
     -- class the fold/scalar mechanism regulates; see homeostatic.py).
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
