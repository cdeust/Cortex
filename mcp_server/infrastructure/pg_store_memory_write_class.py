"""``memories.write_class`` one-shot historical backfill DB operations
(M-D2, 7.4).

Reads distinct ``source`` groups still holding the column's DEFAULT
(``'deliberate'``) — the sentinel every pre-7.4 row got from the
migration (``infrastructure/pg_schema.py`` MIGRATIONS_DDL) — and rewrites
matching rows to their source-inferred class. Split into its own module,
mirroring ``pg_store_memory_domain.py``'s precedent for the same problem
shape (I6-D3): pure infrastructure (no core imports), one query + one
bulk UPDATE, both guarded at the SQL level so re-running is a no-op by
construction, not by application-level bookkeeping.

Group-by-source, not per-row: ``classify_write_class`` is a pure function
of ``source`` alone, so every row sharing a ``source`` value shares the
same target class — one UPDATE per distinct source touches every
matching row in one statement instead of N row-by-row writes. Distinct
source cardinality is bounded (measured DB: low thousands at most across
the whole taxonomy — backfill:<slug> is one per scanned directory,
wiki://<rel_path> is one per wiki page — orders of magnitude below the
row count).

Scoped to ``write_class = 'deliberate'`` ONLY (the DEFAULT sentinel):
a row that a post-7.4 writer explicitly set to a DIFFERENT class is never
touched here regardless of what its ``source`` string implies — this
backfill only resolves rows that never received an explicit
classification, it never overrides one. A row explicitly written as
``write_class='deliberate'`` with a source that would otherwise imply a
different class (a rare, deliberate override) is indistinguishable from
an unclassified historical row and WILL be reclassified by this pass —
documented residual risk, bounded to the narrow window between the
schema migration landing and this one-shot script's first run (see
``scripts/backfill_write_class.py`` module docstring).
"""

from __future__ import annotations

from mcp_server.infrastructure.row_factory import DICT_ROW

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp_server.infrastructure.db_types import StoreConnection


_DEFAULT_SENTINEL = "deliberate"


def list_source_groups_at_default(conn: StoreConnection, limit: int) -> list[dict]:
    """Distinct ``source`` values among active rows still at the column
    DEFAULT, with their row counts.

    Pre-condition:  ``limit`` bounds the number of DISTINCT source groups
                    returned (not row count) — the candidate set this
                    backfill needs to reclassify.
    Post-condition: every returned row carries ``source`` (``''`` for
                    empty/NULL) and ``row_count`` (rows currently at
                    ``write_class = 'deliberate'`` sharing that source).
                    Scoped to ``current_memories`` (chain heads only,
                    matching every other backfill pass's scope) and
                    ``NOT is_stale``. A source group with zero rows still
                    at the sentinel is never returned — re-running after
                    a full apply finds nothing left to reclassify
                    (idempotence).
    """
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
    """Rewrite every active, still-default row sharing ``source`` to
    ``target_class``.

    Pre-condition:  ``target_class`` is one of the four known write
                    classes (validated by the caller — this layer trusts
                    it, same contract as ``pg_store.py::_build_insert_params``;
                    the CHECK constraint on ``memories.write_class`` is
                    the DB-level backstop against a bad value).
    Post-condition: every row with this ``source`` AND
                    ``write_class = 'deliberate'`` (the guard is re-stated
                    at the SQL level, not just in the caller's WHERE from
                    ``list_source_groups_at_default`` — a concurrent
                    writer that already gave the row an explicit,
                    different class between the scan and this UPDATE is
                    never clobbered) now has ``write_class = target_class``.
                    Returns the number of rows actually changed.
    """
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
