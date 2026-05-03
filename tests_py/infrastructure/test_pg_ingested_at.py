"""Schema-shape regression tests for the ingested_at column.

The consolidation-cadence fix (tasks/e1-v3-locomo-smoke-finding.md) adds
``memories.ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`` so that
compression and decay cadence reads ingest-relative time instead of
``created_at`` (which is the original-event time and may be backdated
on backfill).

These tests assert the column declaration, the migration guard, and the
backfill statement are all present in the DDL strings — without
requiring a live PostgreSQL connection.
"""

from __future__ import annotations

from mcp_server.infrastructure.pg_schema import MEMORIES_DDL, MIGRATIONS_DDL


def test_memories_ddl_declares_ingested_at() -> None:
    """Fresh DBs receive ingested_at via the base CREATE TABLE."""
    assert "ingested_at" in MEMORIES_DDL, (
        "MEMORIES_DDL must declare ingested_at on fresh installs"
    )
    assert "ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()" in MEMORIES_DDL, (
        "ingested_at must be NOT NULL DEFAULT NOW() in CREATE TABLE memories"
    )


def test_migration_adds_ingested_at_when_missing() -> None:
    """Existing DBs receive ingested_at via the idempotent migration."""
    # Guard: only ALTER if column not already present.
    assert "column_name = 'ingested_at'" in MIGRATIONS_DDL, (
        "ingested_at migration must guard with information_schema lookup"
    )
    assert "ALTER TABLE memories ADD COLUMN ingested_at" in MIGRATIONS_DDL, (
        "ingested_at migration must ALTER TABLE ADD COLUMN"
    )


def test_migration_backfills_from_created_at() -> None:
    """Pre-existing rows backfill ingested_at = created_at.

    Ensures the migration is semantically transparent for memories that
    predate the column: their cadence remains created_at-equivalent
    (the rationale recorded in tasks/e1-v3-locomo-smoke-finding.md).
    """
    assert "UPDATE memories SET ingested_at = created_at" in MIGRATIONS_DDL, (
        "ingested_at migration must backfill from created_at"
    )


def test_migration_comment_has_no_semicolons() -> None:
    """DDL comments must not contain semicolons.

    _split_statements() splits the MIGRATIONS block on ``;`` (when no
    ``$$`` is in the block) — a stray ``;`` in a comment splits the
    statement mid-comment. df14e16 and 9f94bd3 are prior incidents.
    The migrations block does contain ``$$`` (DO blocks), so it ships
    as a single statement; this test guards the invariant in case the
    block structure ever changes.
    """
    # Find the ingested_at migration block.
    needle = "Migration: add ingested_at"
    start = MIGRATIONS_DDL.find(needle)
    assert start != -1, "ingested_at migration block not found"
    # Read forward to the end of the comment header (the DO block).
    end = MIGRATIONS_DDL.find("DO $$", start)
    comment_block = MIGRATIONS_DDL[start:end]
    assert ";" not in comment_block, (
        f"ingested_at migration comment contains a semicolon (would break "
        f"_split_statements if $$ guards are removed): {comment_block!r}"
    )
