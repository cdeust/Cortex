"""wiki.pages bulk thermodynamic-update DB operations.

Split out of ``pg_store_wiki.py`` (originally 890 lines, over the
300-line file limit — CLAUDE.md "Code Quality Rules") purely for size
compliance; no logic changed.

Pure infrastructure — no core imports, no handler imports.
"""

from __future__ import annotations

from mcp_server.infrastructure.row_factory import DICT_ROW

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection


def list_pages_for_decay(
    conn: StoreConnection,
    *,
    limit: int = 5000,
    include_archived: bool = False,
) -> list[dict]:
    """Pages eligible for a thermodynamic sweep.

    Skips evergreen by default (never decays) and archived unless
    ``include_archived`` is True (only useful to detect revivals,
    which we handle via the citation trigger anyway).
    """
    states = ["active", "area"]
    if include_archived:
        states.append("archived")
    sql = """
    SELECT id, heat, lifecycle_state, tended, is_stale, lead, sections
      FROM wiki.pages
     WHERE lifecycle_state = ANY(%s)
     ORDER BY id LIMIT %s
    """
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(sql, (states, limit))
        return list(cur.fetchall())


def apply_thermo_decisions(conn: StoreConnection, decisions: list[Any]) -> int:
    """Bulk apply HeatDecision rows. Returns count of pages written.

    Idempotent — UPDATE only fires when at least one of (heat,
    lifecycle_state, archived_at) differs from current.
    """
    if not decisions:
        return 0
    written = 0
    with conn.cursor() as cur:
        for d in decisions:
            cur.execute(
                """
                UPDATE wiki.pages
                   SET heat = %s,
                       lifecycle_state = %s,
                       archived_at = COALESCE(%s::timestamptz, archived_at),
                       tended = NOW()
                 WHERE id = %s
                   AND (
                     ABS(heat - %s) > 0.001
                     OR lifecycle_state <> %s
                     OR (%s::timestamptz IS NOT NULL AND archived_at IS NULL)
                   )
                """,
                (
                    d.new_heat,
                    d.new_lifecycle,
                    d.archived_at,
                    d.page_id,
                    d.new_heat,
                    d.new_lifecycle,
                    d.archived_at,
                ),
            )
            written += cur.rowcount
    return written


def apply_staleness_decisions(conn: StoreConnection, decisions: list[Any]) -> int:
    """Bulk apply StalenessDecision rows. Returns transitions written."""
    if not decisions:
        return 0
    written = 0
    with conn.cursor() as cur:
        for d in decisions:
            if not d.transitioned:
                continue
            cur.execute(
                "UPDATE wiki.pages SET is_stale = %s WHERE id = %s",
                (d.is_stale_now, d.page_id),
            )
            written += cur.rowcount
    return written


def get_claim_file_refs_for_pages(
    conn: StoreConnection, page_ids: list[int]
) -> dict[int, list[str]]:
    """For each page, return the file paths cited by its source memory's claims.

    Joins wiki.pages → memories → wiki.claim_events; pulls evidence_refs
    of kind='file'. Returns {page_id: [file_path, ...]}.
    """
    if not page_ids:
        return {}
    sql = """
    SELECT p.id AS page_id,
           c.evidence_refs
      FROM wiki.pages p
      JOIN wiki.claim_events c ON c.memory_id = p.memory_id
     WHERE p.id = ANY(%s)
    """
    out: dict[int, set[str]] = {}
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(sql, (list(page_ids),))
        for row in cur.fetchall():
            page_id = row["page_id"]
            refs = row["evidence_refs"] or []
            for ref in refs:
                if isinstance(ref, dict) and ref.get("kind") == "file":
                    out.setdefault(page_id, set()).add(ref["target"])
    return {k: sorted(v) for k, v in out.items()}
