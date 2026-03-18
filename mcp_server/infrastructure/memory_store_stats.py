"""Stats, diagnostics, consolidation stage, and oscillatory state mixin."""

from __future__ import annotations

import sqlite3
from typing import Any


class MemoryStatsMixin:
    """Diagnostics, dashboard queries, consolidation stages, and more.

    Requires _conn (sqlite3.Connection) and _row_to_dict on the host class.
    """

    _conn: sqlite3.Connection

    # ── Counts & Averages ──────────────────────────────────────────────

    def count_memories(self) -> dict[str, int]:
        row = self._conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN store_type = 'episodic' THEN 1 ELSE 0 END) as episodic,
                SUM(CASE WHEN store_type = 'semantic' THEN 1 ELSE 0 END) as semantic,
                SUM(CASE WHEN heat >= 0.05 THEN 1 ELSE 0 END) as active,
                SUM(CASE WHEN heat < 0.05 THEN 1 ELSE 0 END) as archived,
                SUM(CASE WHEN is_stale = 1 THEN 1 ELSE 0 END) as stale,
                SUM(CASE WHEN is_protected = 1 THEN 1 ELSE 0 END) as protected
            FROM memories
        """).fetchone()
        return dict(row) if row else {}

    def get_avg_heat(self) -> float:
        row = self._conn.execute(
            "SELECT AVG(heat) as avg_heat FROM memories"
        ).fetchone()
        return row["avg_heat"] or 0.0 if row else 0.0

    def get_domain_counts(self) -> dict[str, int]:
        """Get memory count grouped by domain."""
        rows = self._conn.execute(
            "SELECT domain, COUNT(*) as c FROM memories "
            "WHERE is_stale = 0 GROUP BY domain"
        ).fetchall()
        return {(r["domain"] or "unclassified"): r["c"] for r in rows}

    # ── Dashboard Queries ──────────────────────────────────────────────

    def get_recent_memories(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get most recently created memories."""
        rows = self._conn.execute(
            "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_recently_accessed_memories(
        self, limit: int = 20, min_access_count: int = 1
    ) -> list[dict[str, Any]]:
        """Get recently accessed memories for SR co-access graph."""
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE access_count >= ? "
            "AND is_stale = 0 ORDER BY last_accessed DESC LIMIT ?",
            (min_access_count, limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    # ── Consolidation Stage ────────────────────────────────────────────

    def update_memory_consolidation(
        self,
        memory_id: int,
        stage: str,
        hours_in_stage: float,
        replay_count: int,
        hippocampal_dependency: float,
    ) -> None:
        """Update consolidation cascade state for a memory."""
        self._conn.execute(
            "UPDATE memories SET consolidation_stage = ?, "
            "hours_in_stage = ?, replay_count = ?, "
            "hippocampal_dependency = ? WHERE id = ?",
            (stage, hours_in_stage, replay_count, hippocampal_dependency, memory_id),
        )
        self._conn.commit()

    def get_memories_by_stage(
        self, stage: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get memories in a specific consolidation stage."""
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE consolidation_stage = ? "
            "ORDER BY hours_in_stage DESC LIMIT ?",
            (stage, limit),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_stage_counts(self) -> dict[str, int]:
        """Count memories per consolidation stage."""
        rows = self._conn.execute(
            "SELECT consolidation_stage, COUNT(*) as c FROM memories "
            "GROUP BY consolidation_stage"
        ).fetchall()
        return {r["consolidation_stage"]: r["c"] for r in rows}

    def increment_replay_count(self, memory_id: int) -> None:
        self._conn.execute(
            "UPDATE memories SET replay_count = replay_count + 1 WHERE id = ?",
            (memory_id,),
        )
        self._conn.commit()

    # ── Oscillatory State ──────────────────────────────────────────────

    def save_oscillatory_state(self, state_json: str) -> None:
        """Persist oscillatory clock state (singleton row)."""
        self._conn.execute(
            "INSERT OR REPLACE INTO oscillatory_state (id, state_json) VALUES (1, ?)",
            (state_json,),
        )
        self._conn.commit()

    def load_oscillatory_state(self) -> str | None:
        """Load persisted oscillatory state, or None if never saved."""
        row = self._conn.execute(
            "SELECT state_json FROM oscillatory_state WHERE id = 1"
        ).fetchone()
        return row["state_json"] if row else None

    # ── Interference ───────────────────────────────────────────────────

    def get_similar_memories_for_interference(
        self, domain: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get memories with embeddings for interference detection."""
        rows = self._conn.execute(
            "SELECT id, embedding, heat, importance, "
            "consolidation_stage, directory_context, interference_score "
            "FROM memories WHERE domain = ? AND embedding IS NOT NULL "
            "AND is_stale = 0 ORDER BY heat DESC LIMIT ?",
            (domain, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_memory_interference(
        self,
        memory_id: int,
        interference_score: float,
        separation_index: float | None = None,
    ) -> None:
        """Update interference metrics for a memory."""
        if separation_index is not None:
            self._conn.execute(
                "UPDATE memories SET interference_score = ?, "
                "separation_index = ? WHERE id = ?",
                (interference_score, separation_index, memory_id),
            )
        else:
            self._conn.execute(
                "UPDATE memories SET interference_score = ? WHERE id = ?",
                (interference_score, memory_id),
            )
        self._conn.commit()

    # ── CLS Queries ────────────────────────────────────────────────────

    def get_episodic_memories(
        self, domain: str = "", directory: str = "", limit: int = 500
    ) -> list[dict[str, Any]]:
        """Get episodic memories, optionally filtered."""
        conditions = ["store_type = 'episodic'", "is_stale = 0"]
        params: list = []
        if domain:
            conditions.append("domain = ?")
            params.append(domain)
        if directory:
            conditions.append("directory_context = ?")
            params.append(directory)
        params.append(limit)
        where = " AND ".join(conditions)
        rows = self._conn.execute(
            f"SELECT * FROM memories WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_semantic_memories(
        self, domain: str = "", limit: int = 500
    ) -> list[dict[str, Any]]:
        """Get semantic memories, optionally filtered by domain."""
        if domain:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE store_type = 'semantic' "
                "AND domain = ? AND is_stale = 0 "
                "ORDER BY created_at DESC LIMIT ?",
                (domain, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE store_type = 'semantic' "
                "AND is_stale = 0 ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update_memory_store_type(self, memory_id: int, store_type: str) -> None:
        """Change a memory's store type (episodic / semantic)."""
        self._conn.execute(
            "UPDATE memories SET store_type = ? WHERE id = ?",
            (store_type, memory_id),
        )
        self._conn.commit()

    # ── Consolidation Log ──────────────────────────────────────────────

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    def log_consolidation(self, data: dict[str, Any]) -> int:
        now = self._now_iso()
        cursor = self._conn.execute(
            "INSERT INTO consolidation_log "
            "(timestamp, memories_added, memories_updated, "
            "memories_archived, duration_ms) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                now,
                data.get("memories_added", 0),
                data.get("memories_updated", 0),
                data.get("memories_archived", 0),
                data.get("duration_ms", 0),
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    def get_last_consolidation(self) -> str | None:
        row = self._conn.execute(
            "SELECT timestamp FROM consolidation_log ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return row["timestamp"] if row else None

    # ── Active Triggers Count ──────────────────────────────────────────

    def count_active_triggers(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) as c FROM prospective_memories WHERE is_active = 1"
        ).fetchone()
        return row["c"] if row else 0
