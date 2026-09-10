"""source: ADR-0556"""

from __future__ import annotations

from mcp_server.infrastructure.row_factory import DICT_ROW

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection


_DEFAULT_SENTINEL = "deliberate"


def list_source_groups_at_default(conn: StoreConnection, limit: int) -> list[dict]:
    """Count active source groups still classified as deliberate.

    Pre-condition: limit bounds distinct source groups, not member rows.

    Post-condition: return source (empty string for NULL/empty) and row_count
    for non-stale current_memories still at write_class=deliberate. Omit
    groups with no matching rows.

    source: ADR-0556"""
    sql = (
        "SELECT COALESCE(source, '') AS source, COUNT(*) AS row_count\n"
        "  FROM current_memories\n"
        " WHERE write_class = %(sentinel)s\n"
        "   AND NOT is_stale\n"
        " GROUP BY source\n"
        " ORDER BY source\n"
        " LIMIT %(limit)s"
    )
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(sql, {"sentinel": _DEFAULT_SENTINEL, "limit": limit})
        return list(cur.fetchall())


def bulk_reclassify_source(
    conn: StoreConnection, source: str, target_class: str
) -> int:
    """Reclassify still-deliberate active rows sharing source.

    Pre-condition: target_class is a known write class validated by the
    caller.

    Post-condition: set write_class to target_class only for matching rows
    still classified deliberate. Preserve rows concurrently moved to another
    class. Return the number of changed rows.

    source: ADR-0556"""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE memories
                  SET write_class = %(target)s
                WHERE COALESCE(source, '') = %(source)s
                  AND write_class = %(sentinel)s""",
            {
                "target": target_class,
                "source": source,
                "sentinel": _DEFAULT_SENTINEL,
            },
        )
        return cur.rowcount


__all__ = [
    "list_source_groups_at_default",
    "bulk_reclassify_source",
]
