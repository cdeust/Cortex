"""Pure infrastructure — no core imports, no handler imports.

source: ADR-0552"""

from __future__ import annotations

from mcp_server.infrastructure.row_factory import DICT_ROW

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing_extensions import LiteralString
    from mcp_server.infrastructure.db_types import StoreConnection


# source: ADR-0552
DEFAULT_DEDUP_SCAN_LIMIT = 5000


def _dup_key_expr(column: str) -> str:
    """SQL expression for the exact-duplicate grouping key on ``column``.

    source: ADR-0552"""
    return f"md5(lower(regexp_replace({column}, '\\s+', ' ', 'g')))"


def list_exact_duplicate_groups(conn: StoreConnection, limit: int) -> list[dict]:
    """List members of active exact-duplicate groups.

    Pre-condition: limit bounds member rows, not groups.

    Post-condition: return dup_key, id, effective_heat, created_at, domain,
    and tags for non-stale current_memories belonging to groups of at least
    two. Heat uses the row domain factor, defaulting to 1.0. Order by dup_key
    then id.

    source: ADR-0552"""
    # source: ADR-0552
    sql = f"""
        WITH dup_keys AS (
            SELECT {_dup_key_expr("content")} AS dup_key
              FROM current_memories
             WHERE NOT is_stale
             GROUP BY 1
            HAVING COUNT(*) > 1
        ),
        candidates AS (
            -- source: ADR-0552
            SELECT m.*
              FROM current_memories m
             WHERE NOT m.is_stale
        )
        SELECT c.id,
               {_dup_key_expr("c.content")} AS dup_key,
               effective_heat(c, NOW(), COALESCE(hs.factor, 1.0))::REAL
                   AS effective_heat,
               c.created_at,
               c.domain,
               c.tags
          FROM candidates c
          JOIN dup_keys dk ON dk.dup_key = {_dup_key_expr("c.content")}
     -- source: ADR-0552
     LEFT JOIN homeostatic_state hs ON hs.domain = c.domain AND hs.write_class = 'auto'
         ORDER BY dk.dup_key, c.id
         LIMIT %(limit)s
    """  # noqa: S608 — expression from hardcoded identifiers only (documented contract at _dup_key_expr); values are bound parameters (docs/ASSURANCE-CASE.md §5)
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(cast("LiteralString", sql), {"limit": limit})
        return list(cur.fetchall())


def supersede_to_existing(
    conn: StoreConnection, duplicate_id: int, survivor_id: int
) -> bool:
    """Point a duplicate memory at an existing survivor without inserting a row.

    Pre-condition: duplicate_id != survivor_id.

    Post-condition: return True and set duplicate.superseded_by_id only if
    both rows are still chain heads. Otherwise return False without writing.
    Do not modify content, tags, domain, any other duplicate column, or the
    survivor’s supersedes_id.

    source: ADR-0552"""
    if duplicate_id == survivor_id:
        raise ValueError("supersede_to_existing: duplicate_id == survivor_id")
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE memories
                  SET superseded_by_id = %(survivor_id)s
                WHERE id = %(duplicate_id)s
                  AND superseded_by_id IS NULL
                  AND EXISTS (
                        SELECT 1 FROM memories s
                         WHERE s.id = %(survivor_id)s
                           AND s.superseded_by_id IS NULL
                      )""",
            {"duplicate_id": duplicate_id, "survivor_id": survivor_id},
        )
        return cur.rowcount > 0


__all__ = [
    "DEFAULT_DEDUP_SCAN_LIMIT",
    "list_exact_duplicate_groups",
    "supersede_to_existing",
]
