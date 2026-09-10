"""Read-only query for lesson-promotion candidates (M-D6, INC 7.6).

source: ADR-0551"""

from __future__ import annotations

from mcp_server.infrastructure.row_factory import DICT_ROW

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection


# source: ADR-0551
_ELIGIBLE_WHERE = """
    NOT m.is_stale
      AND (
        m.tags @> '["lesson"]'::jsonb
        OR m.tags @> '["lesson-candidate"]'::jsonb
      )
      AND (m.access_count > 0 OR m.useful_count > 0)
      AND NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(m.tags) t
        WHERE t LIKE 'promoted:%%'
      )
"""


def list_lesson_promotion_candidates(
    conn: StoreConnection, limit: int = 20
) -> list[dict[str, Any]]:
    """Precondition: none — works on any schema-provisioned DB, even with
        zero lesson-tagged rows. Postcondition: returns memories tagged 'lesson' or
        'lesson-candidate',
        not stale, not already carrying a 'promoted:*' tag, with
        access_count > 0 OR useful_count > 0 (at least one real recall
        surfacing or rating event — a structural zero/nonzero boundary, not
        a tuned magnitude threshold), ordered by useful_count then
        access_count descending so the most-validated lessons surface
        first.

    source: ADR-0551"""
    sql = f"""
    SELECT m.id, LEFT(m.content, 500) AS content_preview, m.domain,
           m.tags, m.useful_count, m.access_count, m.created_at
    FROM current_memories m
    WHERE {_ELIGIBLE_WHERE}
    ORDER BY m.useful_count DESC, m.access_count DESC, m.created_at DESC
    LIMIT %s;
    """  # noqa: S608 — interpolated fragment is the module-level literal _ELIGIBLE_WHERE; values are bound parameters (docs/ASSURANCE-CASE.md §5)
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(sql, (limit,))
        return list(cur.fetchall())


def count_lesson_promotion_candidates(conn: StoreConnection) -> int:
    """Total count of lesson-promotion candidates, unbounded by any limit.

    Precondition: same as ``list_lesson_promotion_candidates``. Postcondition: returns
    the exact row count matching
        ``_ELIGIBLE_WHERE`` — the same eligibility definition
        ``list_lesson_promotion_candidates`` uses, just without a ``LIMIT``
        truncating it.

    source: ADR-0551"""

    sql = f"SELECT count(*) AS n FROM current_memories m WHERE {_ELIGIBLE_WHERE};"  # noqa: S608 — interpolated fragment is the module-level literal _ELIGIBLE_WHERE; values are bound parameters (docs/ASSURANCE-CASE.md §5)
    with conn.cursor(row_factory=DICT_ROW) as cur:
        cur.execute(sql)
        row = cur.fetchone()
        return int(row["n"]) if row else 0
