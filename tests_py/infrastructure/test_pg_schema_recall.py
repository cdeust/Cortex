"""Schema-shape regression tests for the recall_memories PL/pgSQL function.

These run without a live PostgreSQL connection — they simply assert that
the DDL string declares the columns the recall handler depends on. The
``source`` column is required so callers can round-trip a recalled
memory back to its canonical wiki page (``wiki://...``).
"""

from __future__ import annotations

from mcp_server.infrastructure.pg_schema import RECALL_MEMORIES_FN


def test_recall_memories_returns_source_column() -> None:
    """source must be in RETURNS TABLE and selected from memories."""
    assert "source          TEXT" in RECALL_MEMORIES_FN, (
        "recall_memories() RETURNS TABLE must declare source TEXT"
    )
    assert "m.source" in RECALL_MEMORIES_FN, (
        "recall_memories() final SELECT must include m.source"
    )


def test_recall_memories_drop_guard_present() -> None:
    """The function must DROP the prior signature so column changes apply."""
    assert "DROP FUNCTION IF EXISTS recall_memories" in RECALL_MEMORIES_FN, (
        "RECALL_MEMORIES_FN must DROP its prior signature before CREATE — "
        "Postgres rejects column-list changes via CREATE OR REPLACE alone."
    )


def test_recall_memories_returns_known_columns() -> None:
    """Backstop: every column the recall handler reads must be declared."""
    required = (
        "memory_id",
        "content",
        "score",
        "heat",
        "domain",
        "created_at",
        "store_type",
        "tags",
        "importance",
        "surprise_score",
        "emotional_valence",
        "source",
    )
    for col in required:
        assert col in RECALL_MEMORIES_FN, f"missing column in RETURNS TABLE: {col}"
