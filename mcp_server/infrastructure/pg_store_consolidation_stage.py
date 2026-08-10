"""Consolidation-stage mixin for PgMemoryStore: cascade stage transitions.

Split out of pg_store_stats.py (issue #407: 406 lines over the
300-line §4.1 cap) — the LABILE→EARLY_LTP→LATE_LTP→CONSOLIDATED
cascade's stage writes/reads (Kandel 2001) are their own concern,
distinct from counts/dashboard (``pg_store_stats``) and CLS/
oscillatory/interference queries (``pg_store_cls``).
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.pg_store_host import PgStoreHost


class PgConsolidationStageMixin(PgStoreHost):
    """Cascade consolidation-stage writers/readers on PostgreSQL."""

    def update_memory_consolidation(
        self,
        memory_id: int,
        stage: str,
        hours_in_stage: float,
        replay_count: int,
        hippocampal_dependency: float,
    ) -> None:
        self._execute(
            "UPDATE memories SET consolidation_stage = %s, "
            "hours_in_stage = %s, replay_count = %s, "
            "hippocampal_dependency = %s WHERE id = %s",
            (stage, hours_in_stage, replay_count, hippocampal_dependency, memory_id),
        )
        self._conn.commit()

    def insert_stage_transitions_batch(self, rows: list[dict]) -> int:
        """Batch-insert cascade stage-transition rows in a single statement.

        Source: issue #13 — was per-row INSERT + per-row commit inside the
        cascade loop (503 fsyncs on darval's run).
        """
        if not rows:
            return 0
        memory_ids = [int(r["memory_id"]) for r in rows]
        from_stages = [str(r["from_stage"]) for r in rows]
        to_stages = [str(r["to_stage"]) for r in rows]
        hours = [float(r["hours_in_prev"]) for r in rows]
        triggers = [str(r.get("trigger", "cascade")) for r in rows]
        self._execute(
            "INSERT INTO stage_transitions "
            "(memory_id, from_stage, to_stage, hours_in_prev_stage, trigger) "
            "SELECT * FROM UNNEST("
            "  %s::int[], %s::text[], %s::text[], %s::real[], %s::text[]"
            ")",
            (memory_ids, from_stages, to_stages, hours, triggers),
        )
        self._conn.commit()
        return len(rows)

    def get_memories_by_stage(
        self, stage: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM memories WHERE consolidation_stage = %s "
            "ORDER BY hours_in_stage DESC LIMIT %s",
            (stage, limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_stage_counts(self) -> dict[str, int]:
        rows = self._execute(
            "SELECT consolidation_stage, COUNT(*) AS c FROM memories "
            "GROUP BY consolidation_stage"
        ).fetchall()
        return {r["consolidation_stage"]: r["c"] for r in rows}

    def increment_replay_count(self, memory_id: int) -> dict[str, Any] | None:
        """Increment replay_count and return the post-increment CLS-B inputs.

        Returns ``{"replay_count", "hippocampal_dependency", "schema_match_score",
        "importance"}`` read back atomically via ``RETURNING`` (single round
        trip — the caller needs the just-incremented count, not a stale one),
        or ``None`` if the memory no longer exists. Pure persistence: the
        caller (handler layer) decides what, if anything, to do with these
        values.
        """
        row = self._execute(
            "UPDATE memories SET replay_count = replay_count + 1 WHERE id = %s "
            "RETURNING replay_count, hippocampal_dependency, "
            "schema_match_score, importance",
            (memory_id,),
        ).fetchone()
        self._conn.commit()
        return dict(row) if row else None

    def update_memory_hippocampal_dependency(
        self, memory_id: int, dependency: float
    ) -> None:
        """Persist a new hippocampal_dependency value. No policy — pure write."""
        self._execute(
            "UPDATE memories SET hippocampal_dependency = %s WHERE id = %s",
            (dependency, memory_id),
        )
        self._conn.commit()

    def log_consolidation(self, data: dict[str, Any]) -> int:
        row = self._execute(
            "INSERT INTO consolidation_log "
            "(memories_added, memories_updated, memories_archived, duration_ms) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (
                data.get("memories_added", 0),
                data.get("memories_updated", 0),
                data.get("memories_archived", 0),
                data.get("duration_ms", 0),
            ),
        ).one()
        self._conn.commit()
        return row["id"]

    def get_last_consolidation(self) -> str | None:
        row = self._execute(
            "SELECT timestamp FROM consolidation_log ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return row["timestamp"].isoformat() if row else None
