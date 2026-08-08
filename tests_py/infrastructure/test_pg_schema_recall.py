"""Schema-shape regression tests for the A3 recall_memories PL/pgSQL function.

These run without a live PostgreSQL connection — they simply assert that
the DDL string declares the columns the recall handler depends on. The
``source`` column is required so callers can round-trip a recalled
memory back to its canonical wiki page (``wiki://...``).

Post-A3: the canonical recall function is ``RECALL_MEMORIES_LAZY_FN``.
The legacy ``RECALL_MEMORIES_FN`` has been deleted.
"""

from __future__ import annotations

import re

from mcp_server.infrastructure.pg_schema import (
    MEMORIES_DDL,
    MIGRATIONS_DDL,
    RECALL_MEMORIES_LAZY_FN,
)


def test_recall_memories_returns_source_column() -> None:
    """source must be in RETURNS TABLE and selected from memories."""
    assert "source          TEXT" in RECALL_MEMORIES_LAZY_FN, (
        "recall_memories() RETURNS TABLE must declare source TEXT"
    )
    # Pin the alias the DDL actually uses: the final SELECT reads from the
    # candidates CTE (`c.source`). A former `or "m.source"` arm never matched
    # (verified against RECALL_MEMORIES_LAZY_FN, 2026-07-28) and only
    # weakened the assertion — boy-scout fix, #197 family-3 sweep.
    assert "c.source" in RECALL_MEMORIES_LAZY_FN, (
        "recall_memories() final SELECT must include the source column"
    )


def test_recall_memories_drop_guard_present() -> None:
    """The function must DROP the prior signature so column changes apply."""
    assert "DROP FUNCTION IF EXISTS recall_memories" in RECALL_MEMORIES_LAZY_FN, (
        "RECALL_MEMORIES_LAZY_FN must DROP its prior signature before CREATE — "
        "Postgres rejects column-list changes via CREATE OR REPLACE alone."
    )


def test_recall_memories_excludes_auto_captures_from_heat_and_recency() -> None:
    """Bounded-io Phase 2 F2 (docs/provenance/bounded-io-phase2-design.md M2):
    auto-capture freshness is a write-frequency artifact, not importance —
    both mechanical pools must exclude source='post_tool_capture'."""
    assert RECALL_MEMORIES_LAZY_FN.count("c.source <> 'post_tool_capture'") == 2, (
        "hot and recency CTEs must each exclude post_tool_capture"
    )


def test_recall_memories_applies_confidence_prior() -> None:
    """Metamemory confidence is a multiplicative document prior
    (Kraaij, Westerveld & Hiemstra 2002) — the M3 feedback channel."""
    assert "confidence_weighted" in RECALL_MEMORIES_LAZY_FN
    assert "COALESCE(c.confidence, 1.0)" in RECALL_MEMORIES_LAZY_FN


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
        assert col in RECALL_MEMORIES_LAZY_FN, f"missing column in RETURNS TABLE: {col}"


def test_memories_ddl_declares_supersession_columns() -> None:
    """Item 1: explicit supersession edges are columns on the base table
    (fresh installs) — both nullable, self-referential FK."""
    assert "supersedes_id" in MEMORIES_DDL
    assert "superseded_by_id" in MEMORIES_DDL
    assert "REFERENCES memories(id) ON DELETE SET NULL" in MEMORIES_DDL


def test_migration_adds_supersession_columns_idempotently() -> None:
    """Existing DBs gain the columns via an idempotent information_schema-
    guarded DO block (same pattern as agent_context / is_global)."""
    for col in ("supersedes_id", "superseded_by_id"):
        assert f"column_name = '{col}'" in MIGRATIONS_DDL, (
            f"migration must guard-check {col}"
        )
        assert f"ALTER TABLE memories ADD COLUMN {col} INTEGER" in MIGRATIONS_DDL, (
            f"migration must add {col}"
        )


def test_recall_demotes_superseded_versions() -> None:
    """Head-of-chain demotion is a constant-free tier sort: superseded
    versions (superseded_by_id IS NOT NULL) rank below current ones.

    The score alias is whichever CTE currently ends the post-fusion chain
    (`tw` since issue #368 appended trust_weighted after confidence_weighted).
    Asserted as a regex on the tier key rather than on that alias: the
    property under test is that the supersession tier is the FIRST sort key,
    which must survive appending another multiplicative link — and pinning
    the alias made this test fail for a rename that changed no behaviour.
    """
    assert re.search(
        r"ORDER BY \(c\.superseded_by_id IS NOT NULL\), \w+\.final_score DESC",
        RECALL_MEMORIES_LAZY_FN,
    ), "final SELECT must tier-sort current versions above superseded ones"
