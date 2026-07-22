"""Read-only SQLite query for lesson-promotion candidates.

SQLite twin of ``pg_store_lesson_promotion.count_lesson_promotion_
candidates`` -- same ``current_memories`` view, same eligibility
semantics, same read-only contract. A separate module (not a branch in
the PG one) because the PG SQL is untranslatable mechanically: ``@>``
and ``jsonb_array_elements_text`` have no SQLite equivalent, and the
psycopg-compat wrapper deliberately translates only lexical conventions
(sqlite_compat.py's translation table), never jsonb operators. The
composition root (handlers/get_grooming_health.py) dispatches on the
store type.
"""

from __future__ import annotations

from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection

# Same eligibility definition as pg_store_lesson_promotion._ELIGIBLE_WHERE,
# expressed with json_each: not stale, tagged 'lesson' or
# 'lesson-candidate', at least one recall/rating event, and no
# 'promoted:*' tag yet. Kept as one shared constant for the same
# anti-drift reason as the PG twin.
_ELIGIBLE_WHERE = """
    NOT m.is_stale
      AND (
        EXISTS (SELECT 1 FROM json_each(m.tags) WHERE value = 'lesson')
        OR EXISTS (SELECT 1 FROM json_each(m.tags)
                   WHERE value = 'lesson-candidate')
      )
      AND (m.access_count > 0 OR m.useful_count > 0)
      AND NOT EXISTS (
        SELECT 1 FROM json_each(m.tags) WHERE value LIKE 'promoted:%'
      )
"""


def count_lesson_promotion_candidates(conn: PsycopgCompatConnection) -> int:
    """Total count of lesson-promotion candidates on the SQLite backend.

    Precondition: ``conn`` is a schema-provisioned SQLite store
    connection (works with zero lesson-tagged rows).
    Postcondition: returns the exact row count matching
    ``_ELIGIBLE_WHERE`` -- the same eligibility definition the PG twin
    counts. Read-only.
    """
    row = conn.execute(
        f"SELECT count(*) AS n FROM current_memories m WHERE {_ELIGIBLE_WHERE}"
    ).fetchone()
    return int(row["n"]) if row else 0
