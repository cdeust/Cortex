"""``wiki.citations`` seed-campaign — DB operations (M-D7, INC7.7).

Finds pages whose ``wiki.pages.memory_id`` column already carries a
verified pointer to their authoring memory (see
``core.wiki_citation_seed`` module docstring for why this is the only
reliable source), and the subset of those pairs already present in
``wiki.citations`` (idempotence check for an accurate dry-run count —
the actual write in ``insert_citation`` is self-dedupng regardless via
``ON CONFLICT DO NOTHING`` on ``uq_wiki_citations_page_memory``).

Infrastructure — no handler imports, no core-decision logic (that lives
in ``core.wiki_citation_seed.classify_seed_candidates``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection


# Measured 20 rows on the dev DB (2026-07-11); comfortably above any
# realistic corpus size for the filename-encoded-memory_id convention
# (bounded by the number of pages ever migrated via wiki_migrate.py from
# a single source memory, not by total page count).
DEFAULT_SEED_SCAN_LIMIT = 5000


def list_page_memory_seed_candidates(conn: StoreConnection, limit: int) -> list[dict]:
    """Every ``wiki.pages`` row with a non-null, FK-valid ``memory_id``.

    Precondition: none beyond a provisioned ``wiki`` schema.
    Postcondition: returns at most ``limit`` rows, each
    ``{page_id, memory_id, domain}``, ordered by ``page_id`` for
    deterministic pagination across dry-run/apply re-runs. The join
    to ``memories`` is redundant with the column's own
    ``REFERENCES memories(id)`` constraint (a dangling FK cannot exist)
    but is kept explicit so a future ``ON DELETE SET NULL`` semantics
    change cannot silently admit a stale id without this query
    reflecting it.
    """
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

    sql = """
    SELECT p.id AS page_id, p.memory_id AS memory_id,
           p.domain AS domain
    FROM wiki.pages p
    JOIN memories m ON m.id = p.memory_id
    WHERE p.memory_id IS NOT NULL
    ORDER BY p.id
    LIMIT %s;
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (limit,))
        return list(cur.fetchall())


def list_existing_page_memory_citations(
    conn: StoreConnection, page_ids: list[int]
) -> set[tuple[int, int]]:
    """(page_id, memory_id) pairs already recorded in ``wiki.citations``.

    Precondition: ``page_ids`` is the exact candidate set from
    ``list_page_memory_seed_candidates`` (scoping the query keeps it
    cheap and keeps the returned set exactly comparable to
    ``core.wiki_citation_seed.classify_seed_candidates``'s input
    contract).
    Postcondition: returns every ``(page_id, memory_id)`` pair with
    ``memory_id IS NOT NULL`` already present for the given pages —
    an empty set on a fresh DB (matches "wiki.citations = 0" at design
    time), and after ``--apply`` a set equal to the full candidate list
    (proving idempotence on re-run).
    """
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

    if not page_ids:
        return set()
    sql = """
    SELECT page_id, memory_id
    FROM wiki.citations
    WHERE page_id = ANY(%s) AND memory_id IS NOT NULL;
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (page_ids,))
        return {(row["page_id"], row["memory_id"]) for row in cur.fetchall()}


__all__ = [
    "DEFAULT_SEED_SCAN_LIMIT",
    "list_existing_page_memory_citations",
    "list_page_memory_seed_candidates",
]
