"""``memories`` domain-backfill DB operations (I6-D3).

Pure infrastructure — no core imports, no handler imports.

source: ADR-0553"""

from __future__ import annotations

from mcp_server.infrastructure.row_factory import DICT_ROW

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection


_ORPHAN_TAG = "domain-orphan"


def list_domainless_memories(
    conn: StoreConnection, limit: int, *, include_orphans: bool = False
) -> list[dict]:
    """List current chain-head memories with an empty domain.

    Pre-condition: limit bounds returned rows.

    Post-condition: return id, directory_context (empty when unset), and
    decoded tags. Exclude domain-orphan-tagged rows unless
    include_orphans=True.

    source: ADR-0553"""
    orphan_filter = (
        "" if include_orphans else "AND NOT tags @> '[\"domain-orphan\"]'::jsonb"
    )
    sql = (
        "SELECT id, directory_context, tags\n"  # noqa: S608 — interpolated fragment is an in-code literal ternary; values are bound parameters (docs/ASSURANCE-CASE.md §5)
        "  FROM current_memories\n"
        " WHERE (domain IS NULL OR domain = '')\n"
        f"   {orphan_filter}\n"
        " ORDER BY id\n"
        " LIMIT %(limit)s"
    )
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(sql, {"limit": limit})
        return list(cur.fetchall())


def update_memory_domain(conn: StoreConnection, memory_id: int, domain: str) -> bool:
    """Fill an empty memory domain and remove its orphan tag.

    Pre-condition: memory_id exists and domain is non-empty.

    Post-condition: if the stored domain is NULL or empty, set domain, remove
    domain-orphan from tags, and return True. Otherwise leave the row
    unchanged and return False.

    source: ADR-0553"""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE memories
                  SET domain = %(domain)s,
                      tags = tags - %(orphan_tag)s
                WHERE id = %(id)s
                  AND (domain IS NULL OR domain = '')""",
            {"domain": domain, "id": memory_id, "orphan_tag": _ORPHAN_TAG},
        )
        return cur.rowcount > 0


def tag_memory_orphan(conn: StoreConnection, memory_id: int) -> bool:
    """Tag a memory as domain-orphan without assigning a domain.

    Pre-condition: memory_id identifies an existing row.

    Post-condition: append the tag and return True only when the domain
    remains empty and the tag is absent. Otherwise change nothing and return
    False.

    source: ADR-0553"""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE memories
                  SET tags = tags || %(tag)s::jsonb
                WHERE id = %(id)s
                  AND (domain IS NULL OR domain = '')
                  AND NOT tags @> %(tag)s::jsonb""",
            {"tag": f'["{_ORPHAN_TAG}"]', "id": memory_id},
        )
        return cur.rowcount > 0


__all__ = [
    "list_domainless_memories",
    "update_memory_domain",
    "tag_memory_orphan",
]
