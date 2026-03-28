"""Stats, diagnostics, consolidation, oscillatory state mixin for SqliteMemoryStore."""

from __future__ import annotations

import sqlite3
from typing import Any


class SqliteStatsMixin:
    """Diagnostics, consolidation stages, CLS queries on SQLite."""

    _conn: sqlite3.Connection

    def _normalize_memory_row(self, row: dict) -> dict:
        """Provided by SqliteMemoryStore."""
        return dict(row)

    # ── Counts ────────────────────────────────────────────────────────

    def count_memories(self) -> dict[str, int]:
        row = self._conn.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN store_type = 'episodic' THEN 1 ELSE 0 END) AS episodic,
                SUM(CASE WHEN store_type = 'semantic' THEN 1 ELSE 0 END) AS semantic,
                SUM(CASE WHEN heat >= 0.05 THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN heat < 0.05 THEN 1 ELSE 0 END) AS archived,
                SUM(CASE WHEN is_stale THEN 1 ELSE 0 END) AS stale,
                SUM(CASE WHEN is_protected THEN 1 ELSE 0 END) AS protected
            FROM memories
        """).fetchone()
        if not row:
            return {}
        return {k: (row[k] or 0) for k in row.keys()}

    def get_avg_heat(self) -> float:
        row = self._conn.execute(
            "SELECT AVG(heat) AS avg_heat FROM memories"
        ).fetchone()
        return float(row["avg_heat"] or 0.0) if row else 0.0

    def get_domain_counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT COALESCE(domain, 'unclassified') AS d, COUNT(*) AS c "
            "FROM memories WHERE NOT is_stale GROUP BY domain"
        ).fetchall()
        return {r["d"]: r["c"] for r in rows}

    # ── Dashboard ─────────────────────────────────────────────────────

    def get_recent_memories(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_recently_accessed_memories(
        self, limit: int = 20, min_access_count: int = 1
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE access_count >= ? "
            "AND NOT is_stale ORDER BY last_accessed DESC LIMIT ?",
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
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE consolidation_stage = ? "
            "ORDER BY hours_in_stage DESC LIMIT ?",
            (stage, limit),
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_stage_counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT consolidation_stage, COUNT(*) AS c FROM memories "
            "GROUP BY consolidation_stage"
        ).fetchall()
        return {r["consolidation_stage"]: r["c"] for r in rows}

    def increment_replay_count(self, memory_id: int) -> None:
        self._conn.execute(
            "UPDATE memories SET replay_count = replay_count + 1 WHERE id = ?",
            (memory_id,),
        )
        self._conn.commit()

    # ── Oscillatory State ─────────────────────────────────────────────

    def save_oscillatory_state(self, state_json: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO oscillatory_state (id, state_json) "
            "VALUES (1, ?)",
            (state_json,),
        )
        self._conn.commit()

    def load_oscillatory_state(self) -> str | None:
        row = self._conn.execute(
            "SELECT state_json FROM oscillatory_state WHERE id = 1"
        ).fetchone()
        return row["state_json"] if row else None

    # ── Interference ──────────────────────────────────────────────────

    def get_similar_memories_for_interference(
        self, domain: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, heat, importance, "
            "consolidation_stage, directory_context, interference_score "
            "FROM memories WHERE domain = ? "
            "AND NOT is_stale ORDER BY heat DESC LIMIT ?",
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

    # ── CLS Queries ───────────────────────────────────────────────────

    def get_episodic_memories(
        self, domain: str = "", directory: str = "", limit: int = 500
    ) -> list[dict[str, Any]]:
        conditions = ["store_type = 'episodic'", "NOT is_stale"]
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
            f"SELECT * FROM memories WHERE {where} "
            f"ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_semantic_memories(
        self, domain: str = "", limit: int = 500
    ) -> list[dict[str, Any]]:
        if domain:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE store_type = 'semantic' "
                "AND domain = ? AND NOT is_stale "
                "ORDER BY created_at DESC LIMIT ?",
                (domain, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE store_type = 'semantic' "
                "AND NOT is_stale ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def update_memory_store_type(self, memory_id: int, store_type: str) -> None:
        self._conn.execute(
            "UPDATE memories SET store_type = ? WHERE id = ?",
            (store_type, memory_id),
        )
        self._conn.commit()

    # ── Consolidation Log ─────────────────────────────────────────────

    def log_consolidation(self, data: dict[str, Any]) -> int:
        cur = self._conn.execute(
            "INSERT INTO consolidation_log "
            "(memories_added, memories_updated, memories_archived, duration_ms) "
            "VALUES (?, ?, ?, ?)",
            (
                data.get("memories_added", 0),
                data.get("memories_updated", 0),
                data.get("memories_archived", 0),
                data.get("duration_ms", 0),
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_last_consolidation(self) -> str | None:
        row = self._conn.execute(
            "SELECT timestamp FROM consolidation_log "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return row["timestamp"] if row else None

    def count_active_triggers(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM prospective_memories WHERE is_active"
        ).fetchone()
        return row["c"] if row else 0
