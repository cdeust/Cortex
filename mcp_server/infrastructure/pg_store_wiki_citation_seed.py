"""source: ADR-0572"""

from __future__ import annotations

from mcp_server.infrastructure.row_factory import DICT_ROW

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection


# source: ADR-0572
DEFAULT_SEED_SCAN_LIMIT = 5000


def list_page_memory_seed_candidates(conn: StoreConnection, limit: int) -> list[dict]:
    """Every ``wiki.pages`` row with a non-null, FK-valid ``memory_id``.

    Precondition: none beyond a provisioned ``wiki`` schema. Postcondition: returns at
    most ``limit`` rows, each
        ``{page_id, memory_id, domain}``, ordered by ``page_id`` for
        deterministic pagination across dry-run/apply re-runs.

    source: ADR-0572"""
    sql = """
    SELECT p.id AS page_id, p.memory_id AS memory_id,
           p.domain AS domain
    FROM wiki.pages p
    JOIN memories m ON m.id = p.memory_id
    WHERE p.memory_id IS NOT NULL
    ORDER BY p.id
    LIMIT %s;
    """
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(sql, (limit,))
        return list(cur.fetchall())


def list_existing_page_memory_citations(
    conn: StoreConnection, page_ids: list[int]
) -> set[tuple[int, int]]:
    """Return existing (page_id, memory_id) citation pairs with non-null
    memory_id for the
    supplied page IDs. Returns an empty set when there are no matching citations.

        source: ADR-0572"""
    if not page_ids:
        return set()
    sql = """
    SELECT page_id, memory_id
    FROM wiki.citations
    WHERE page_id = ANY(%s) AND memory_id IS NOT NULL;
    """
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(sql, (page_ids,))
        return {(row["page_id"], row["memory_id"]) for row in cur.fetchall()}


__all__ = [
    "DEFAULT_SEED_SCAN_LIMIT",
    "list_existing_page_memory_citations",
    "list_page_memory_seed_candidates",
]
