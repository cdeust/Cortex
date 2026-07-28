"""``memories`` exact-duplicate collapse — DB operations (I6-D1, INC6.3).

Finds groups of byte-identical active memories (same normalized content,
different rows) and writes supersession edges from every non-survivor
member to the group's elected survivor. Split into its own module for
the same reason as ``pg_store_memory_domain.py`` (I6-D3 precedent): keep
each infrastructure file focused and under the size cap.

Pure infrastructure — no core imports, no handler imports.

Grouping key: ``md5(lower(regexp_replace(content, '\\s+', ' ', 'g')))`` —
the exact expression the I6 audit and the I6-D1 acceptance-criterion SQL
use (case/whitespace-insensitive exact match). Scope: ``current_memories``
(chain heads only) ``WHERE NOT is_stale`` — the same population the
acceptance criterion queries, so a 0-groups-remaining check after
``--apply`` is directly comparable to this module's own scan.

The supersede-to-existing write is a small, explicit extension of the
existing supersession mechanism (``PgMemoryStore.supersede_atomic``,
which always INSERTs a new row): here the "new" row already exists (the
elected survivor), so no INSERT happens — only the CAS-guarded
``superseded_by_id`` stamp that ``supersede_atomic`` also performs.
Design doc I6-D1 names this "un mode batch « supersede-vers-existant »".
Guarded so a race (or a re-run) can never orphan an edge onto a
non-current survivor or double-supersede an already-superseded row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from psycopg import Connection


# Per-run scan cap on GROUP MEMBER ROWS (not groups) — mirrors
# DEFAULT_MEMORY_DOMAIN_BACKFILL_LIMIT's rationale: bounds one run's cost.
# The known stock is 146 rows / 55 groups (I6 audit, re-measured at run
# time by this campaign); comfortably under this cap in one pass.
DEFAULT_DEDUP_SCAN_LIMIT = 5000


def _dup_key_expr(column: str) -> str:
    """SQL expression for the exact-duplicate grouping key on ``column``.

    ``column`` must be a trusted, hardcoded SQL identifier (never
    user input) — the two call sites below pass the literal strings
    ``"content"`` and ``"m.content"``.
    """
    return f"md5(lower(regexp_replace({column}, '\\s+', ' ', 'g')))"


def list_exact_duplicate_groups(conn: Connection, limit: int) -> list[dict]:
    """Every member row of every active exact-duplicate group.

    Pre-condition:  ``limit`` bounds the number of member rows returned
                    (not the number of groups).
    Post-condition: returns one dict per group-member row: ``dup_key``
                    (the group's content hash), ``id``, ``effective_heat``
                    (computed via the ``effective_heat()`` stored
                    function with the row's own domain's homeostatic
                    factor — COALESCE'd to 1.0 for domains with no
                    ``homeostatic_state`` row yet, matching
                    ``get_homeostatic_factor``'s documented default),
                    ``created_at``, ``domain``, ``tags``. Only rows
                    belonging to a group of size >= 2 are returned
                    (``HAVING COUNT(*) > 1``), scoped to
                    ``current_memories WHERE NOT is_stale`` — the exact
                    population the I6-D1 acceptance-criterion SQL checks.
                    Ordered by ``dup_key`` then ``id`` so the caller can
                    group consecutive rows by a single pass
                    (``itertools.groupby``) without an extra sort.
    """
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

    # candidates: re-selects `m.*` into its own CTE before calling
    # effective_heat(). Required, not stylistic — current_memories is a
    # VIEW with its own composite row type, which PostgreSQL will NOT
    # implicitly cast to the `memories` table type effective_heat()
    # expects ("cannot cast type current_memories to memories"). A `SELECT
    # m.*` re-projected through a CTE produces an anonymous RECORD whose
    # column structure PostgreSQL DOES coerce to the target composite
    # type. This is the exact same pattern the production WRRF recall
    # query uses for the same reason (`candidates AS (SELECT m.* FROM
    # current_memories m ...)`, pg_schema.py's recall_memories()).
    sql = f"""
        WITH dup_keys AS (
            SELECT {_dup_key_expr("content")} AS dup_key
              FROM current_memories
             WHERE NOT is_stale
             GROUP BY 1
            HAVING COUNT(*) > 1
        ),
        candidates AS (
            -- `m.*` only (no extra columns) — effective_heat() requires an
            -- exact structural match to the `memories` composite type; see
            -- the module-level comment above for why this CTE hop exists.
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
     -- M-D3 (7.1): homeostatic_state's PK is now (domain, write_class);
     -- pin to 'auto' — the only class ever regulated — or the join fans
     -- out one row per class and effective_heat sees an arbitrary factor.
     LEFT JOIN homeostatic_state hs ON hs.domain = c.domain AND hs.write_class = 'auto'
         ORDER BY dk.dup_key, c.id
         LIMIT %(limit)s
    """  # noqa: S608 — expression from hardcoded identifiers only (documented contract at _dup_key_expr); values are bound parameters (docs/ASSURANCE-CASE.md §5)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"limit": limit})
        return list(cur.fetchall())


def supersede_to_existing(
    conn: Connection, duplicate_id: int, survivor_id: int
) -> bool:
    """Point ``duplicate_id``'s ``superseded_by_id`` at ``survivor_id``,
    CAS-guarded, without inserting any row.

    Pre-condition:  ``duplicate_id != survivor_id``.
    Post-condition: if ``duplicate_id`` was still a chain head
                    (``superseded_by_id IS NULL``) AND ``survivor_id`` is
                    STILL a chain head at write time, ``duplicate_id.
                    superseded_by_id`` is set to ``survivor_id`` and this
                    returns True. Otherwise (duplicate already superseded
                    by a prior run — idempotence — or survivor itself got
                    superseded by a concurrent writer between the scan
                    and this write) nothing is written and this returns
                    False. Never touches ``duplicate_id``'s content,
                    tags, domain, or any other column — pure edge write,
                    matching I6-D1 ("sans créer de nouvelle mémoire ni
                    toucher au contenu"). Does not set the survivor's
                    ``supersedes_id`` (that column is single-valued and
                    already carries the survivor's own prior lineage, if
                    any; the group's full membership remains queryable
                    via ``WHERE superseded_by_id = survivor_id``).
    """
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
