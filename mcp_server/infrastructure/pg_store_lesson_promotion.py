"""Read-only query for lesson-promotion candidates (M-D6, INC 7.6).

Mirrors ``pg_store_wiki_notes.py::list_uncited_deliberate_memories`` —
same ``current_memories`` view, same read-only contract: this module
never writes a rule, a trigger, a page, or a tag. It lists candidates for
``handlers.lesson_promotion`` to package into jobs, exactly as
``curate_wiki_uncited.py`` lists candidates for wiki authoring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection


# Shared by both queries below so the eligibility definition cannot drift
# between the job-listing path and the count-only path (G-2 grooming:
# count_lesson_promotion_candidates reuses this verbatim rather than
# re-deriving an equivalent WHERE clause that could silently disagree).
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
    """List active lesson/lesson-candidate memories with usage evidence.

    Precondition: none — works on any schema-provisioned DB, even with
    zero lesson-tagged rows.
    Postcondition: returns memories tagged 'lesson' or 'lesson-candidate',
    not stale, not already carrying a 'promoted:*' tag, with
    access_count > 0 OR useful_count > 0 (at least one real recall
    surfacing or rating event — a structural zero/nonzero boundary, not
    a tuned magnitude threshold), ordered by useful_count then
    access_count descending so the most-validated lessons surface
    first. Read-only: never mutates memory_rules, prospective_memories,
    wiki.citations, or the memories table itself.
    """
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

    sql = f"""
    SELECT m.id, LEFT(m.content, 500) AS content_preview, m.domain,
           m.tags, m.useful_count, m.access_count, m.created_at
    FROM current_memories m
    WHERE {_ELIGIBLE_WHERE}
    ORDER BY m.useful_count DESC, m.access_count DESC, m.created_at DESC
    LIMIT %s;
    """  # noqa: S608 — interpolated fragment is the module-level literal _ELIGIBLE_WHERE; values are bound parameters (docs/ASSURANCE-CASE.md §5)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (limit,))
        return list(cur.fetchall())


def count_lesson_promotion_candidates(conn: StoreConnection) -> int:
    """Total count of lesson-promotion candidates, unbounded by any limit.

    Precondition: same as ``list_lesson_promotion_candidates``.
    Postcondition: returns the exact row count matching
    ``_ELIGIBLE_WHERE`` — the same eligibility definition
    ``list_lesson_promotion_candidates`` uses, just without a ``LIMIT``
    truncating it. Read-only, single indexed ``COUNT(*)`` (measured
    ~76ms against a 154-page / 3000+ memory dev corpus, 2026-07-11) —
    cheap enough for a per-consolidate-cycle mechanical report — and
    down to ~0.8ms Bitmap Heap Scan with idx_memories_tags_gin
    (pg_schema.py; EXPLAIN ANALYZE 2026-07-11, 11,012 rows) — unlike
    ``curate_distill``'s clustering-derived backlog count (measured
    ~2.6s on the same corpus; see wiki_backlog_pass.py's docstring for
    why that one is NOT wired into the recurring cycle).
    """
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

    sql = f"SELECT count(*) AS n FROM current_memories m WHERE {_ELIGIBLE_WHERE};"  # noqa: S608 — interpolated fragment is the module-level literal _ELIGIBLE_WHERE; values are bound parameters (docs/ASSURANCE-CASE.md §5)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql)
        row = cur.fetchone()
        return int(row["n"]) if row else 0
