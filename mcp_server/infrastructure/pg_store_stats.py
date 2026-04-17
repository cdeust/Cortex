"""Stats, diagnostics, consolidation, oscillatory state mixin for PgMemoryStore."""

from __future__ import annotations

from typing import Any

import psycopg


class PgStatsMixin:
    """Diagnostics, consolidation stages, CLS queries on PostgreSQL."""

    _conn: psycopg.Connection

    def _normalize_memory_row(self, row: dict) -> dict:
        """Provided by PgMemoryStore."""
        return dict(row)

    # ── Counts ────────────────────────────────────────────────────────

    def count_memories(self) -> dict[str, int]:
        row = self._execute("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (WHERE store_type = 'episodic') AS episodic,
                COUNT(*) FILTER (WHERE store_type = 'semantic') AS semantic,
                COUNT(*) FILTER (WHERE heat_base >= 0.05) AS active,
                COUNT(*) FILTER (WHERE heat_base < 0.05) AS archived,
                COUNT(*) FILTER (WHERE is_stale) AS stale,
                COUNT(*) FILTER (WHERE is_protected) AS protected
            FROM memories
        """).fetchone()
        return dict(row) if row else {}

    def get_avg_heat(self) -> float:
        row = self._execute(
            "SELECT AVG(heat_base) AS avg_heat FROM memories"
        ).fetchone()
        return float(row["avg_heat"] or 0.0) if row else 0.0

    def get_domain_counts(self) -> dict[str, int]:
        rows = self._execute(
            "SELECT COALESCE(domain, 'unclassified') AS d, COUNT(*) AS c "
            "FROM memories WHERE NOT is_stale GROUP BY domain"
        ).fetchall()
        return {r["d"]: r["c"] for r in rows}

    # ── Dashboard ─────────────────────────────────────────────────────

    def get_recent_memories(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM memories ORDER BY created_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_recently_accessed_memories(
        self, limit: int = 20, min_access_count: int = 1
    ) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT * FROM memories WHERE access_count >= %s "
            "AND NOT is_stale ORDER BY last_accessed DESC LIMIT %s",
            (min_access_count, limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    # ── Consolidation ─────────────────────────────────────────────────

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

    def increment_replay_count(self, memory_id: int) -> None:
        self._execute(
            "UPDATE memories SET replay_count = replay_count + 1 WHERE id = %s",
            (memory_id,),
        )
        self._conn.commit()

    # ── Oscillatory State ─────────────────────────────────────────────

    def save_oscillatory_state(self, state_json: str) -> None:
        self._execute(
            "INSERT INTO oscillatory_state (id, state_json) VALUES (1, %s) "
            "ON CONFLICT (id) DO UPDATE SET state_json = EXCLUDED.state_json",
            (state_json,),
        )
        self._conn.commit()

    def load_oscillatory_state(self) -> str | None:
        row = self._execute(
            "SELECT state_json FROM oscillatory_state WHERE id = 1"
        ).fetchone()
        return row["state_json"] if row else None

    # ── Interference ──────────────────────────────────────────────────

    def get_similar_memories_for_interference(
        self, domain: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT id, embedding, heat, importance, "
            "consolidation_stage, directory_context, interference_score "
            "FROM memories WHERE domain = %s AND embedding IS NOT NULL "
            "AND NOT is_stale ORDER BY heat DESC LIMIT %s",
            (domain, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_memory_interference(
        self,
        memory_id: int,
        interference_score: float,
        separation_index: float | None = None,
    ) -> None:
        if separation_index is not None:
            self._execute(
                "UPDATE memories SET interference_score = %s, "
                "separation_index = %s WHERE id = %s",
                (interference_score, separation_index, memory_id),
            )
        else:
            self._execute(
                "UPDATE memories SET interference_score = %s WHERE id = %s",
                (interference_score, memory_id),
            )
        self._conn.commit()

    # ── CLS Queries ───────────────────────────────────────────────────

    def get_episodic_memories(
        self, domain: str = "", directory: str = "", limit: int = 500
    ) -> list[dict[str, Any]]:
        conditions = ["store_type = 'episodic'", "NOT is_stale"]
        params: list = []
        if domain:
            conditions.append("domain = %s")
            params.append(domain)
        if directory:
            conditions.append("directory_context = %s")
            params.append(directory)
        params.append(limit)
        where = " AND ".join(conditions)
        rows = self._execute(
            f"SELECT * FROM memories WHERE {where} ORDER BY created_at DESC LIMIT %s",
            params,
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_semantic_memories(
        self, domain: str = "", limit: int = 500
    ) -> list[dict[str, Any]]:
        if domain:
            rows = self._execute(
                "SELECT * FROM memories WHERE store_type = 'semantic' "
                "AND domain = %s AND NOT is_stale "
                "ORDER BY created_at DESC LIMIT %s",
                (domain, limit),
            ).fetchall()
        else:
            rows = self._execute(
                "SELECT * FROM memories WHERE store_type = 'semantic' "
                "AND NOT is_stale ORDER BY created_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def update_memory_store_type(self, memory_id: int, store_type: str) -> None:
        self._execute(
            "UPDATE memories SET store_type = %s WHERE id = %s",
            (store_type, memory_id),
        )
        self._conn.commit()

    # ── Consolidation Log ─────────────────────────────────────────────

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
        ).fetchone()
        self._conn.commit()
        return row["id"]

    def get_last_consolidation(self) -> str | None:
        row = self._execute(
            "SELECT timestamp FROM consolidation_log ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return row["timestamp"].isoformat() if row else None

    def count_active_triggers(self) -> int:
        row = self._execute(
            "SELECT COUNT(*) AS c FROM prospective_memories WHERE is_active"
        ).fetchone()
        return row["c"] if row else 0
