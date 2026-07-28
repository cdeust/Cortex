"""Stats, diagnostics, consolidation, oscillatory state mixin for SqliteMemoryStore."""

from __future__ import annotations

import sqlite3
from mcp_server.infrastructure.sqlite_compat import PsycopgCompatConnection
from typing import Any


class SqliteStatsMixin:
    """Diagnostics, consolidation stages, CLS queries on SQLite."""

    _conn: PsycopgCompatConnection
    _raw_conn: sqlite3.Connection

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
                SUM(CASE WHEN heat_base >= 0.05 THEN 1 ELSE 0 END) AS active,
                SUM(CASE WHEN heat_base < 0.05 THEN 1 ELSE 0 END) AS archived,
                SUM(CASE WHEN is_stale THEN 1 ELSE 0 END) AS stale,
                SUM(CASE WHEN is_protected THEN 1 ELSE 0 END) AS protected
            FROM memories
        """).fetchone()
        if not row:
            return {}
        return {k: (row[k] or 0) for k in row.keys()}

    def get_avg_heat(self) -> float:
        row = self._conn.execute(
            "SELECT AVG(heat_base) AS avg_heat FROM memories"
        ).fetchone()
        return float(row["avg_heat"] or 0.0) if row else 0.0

    def signature_repeat_stats(self, signature: str) -> tuple[int, float | None]:
        """Habituation (E1) read side: prior presentations of a stimulus.

        Returns ``(repeat_count, hours_since_last)`` for memories sharing this
        normalised ``stimulus_signature`` — the count feeds the write gate's
        response decrement (Rankin 2009) and the elapsed hours drive
        spontaneous recovery. ``hours_since_last`` is None when the signature is
        unseen. Best-effort: returns ``(0, None)`` on any error or when the
        column is absent (a store predating habituation), so the gate treats an
        un-migrated store as if nothing has habituated.
        """
        if not signature:
            return 0, None
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c, "
                "MAX(COALESCE(last_accessed, created_at)) AS last_seen "
                "FROM memories WHERE stimulus_signature = ?",
                (signature,),
            ).fetchone()
        except sqlite3.Error:
            return 0, None
        if not row or not row["c"]:
            return 0, None
        count = int(row["c"])
        hours: float | None = None
        last_seen = row["last_seen"]
        if last_seen:
            try:
                from datetime import datetime, timezone

                dt = datetime.fromisoformat(str(last_seen))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
            except (ValueError, TypeError):
                hours = None
        return count, hours

    def extinguished_count(self, threshold: float = 0.5) -> int:
        """Extinction (E2) read side: count of deprecated-but-retained memories.

        Returns how many memories carry an inhibitory extinction tag at or above
        ``threshold`` — the association is suppressed WITHOUT deletion (the row
        is fully present, not is_stale), so it can spontaneously recover or be
        reinstated (Bouton 2004). Best-effort: returns 0 on any error or when
        the ``extinction_strength`` column is absent (a store predating
        extinction), so an un-migrated store reports nothing extinguished.
        """
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM memories "
                "WHERE extinction_strength >= ? AND NOT is_stale",
                (threshold,),
            ).fetchone()
        except sqlite3.Error:
            return 0
        if not row or not row["c"]:
            return 0
        return int(row["c"])

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
        self, limit: int = 20, min_access_count: int = 1, heads_only: bool = False
    ) -> list[dict[str, Any]]:
        """Mirror of PgStatsMixin.get_recently_accessed_memories — heads_only
        routes through the current_memories view (chain heads only).
        """
        src = "current_memories" if heads_only else "memories"
        rows = self._conn.execute(
            f"SELECT * FROM {src} WHERE access_count >= ? "
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

    def insert_stage_transitions_batch(self, rows: list[dict]) -> int:
        """Batch-insert cascade stage-transition rows via executemany."""
        if not rows:
            return 0
        self._raw_conn.executemany(
            "INSERT INTO stage_transitions "
            "(memory_id, from_stage, to_stage, hours_in_prev_stage, trigger) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (
                    int(r["memory_id"]),
                    str(r["from_stage"]),
                    str(r["to_stage"]),
                    float(r["hours_in_prev"]),
                    str(r.get("trigger", "cascade")),
                )
                for r in rows
            ],
        )
        self._conn.commit()
        return len(rows)

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

    def increment_replay_count(self, memory_id: int) -> dict[str, Any] | None:
        """Increment replay_count and return the post-increment CLS-B inputs.

        Returns ``{"replay_count", "hippocampal_dependency", "schema_match_score",
        "importance"}`` read back atomically via ``RETURNING`` (SQLite >= 3.35;
        single round trip — the caller needs the just-incremented count, not a
        stale one), or ``None`` if the memory no longer exists. Pure
        persistence: the caller (handler layer) decides what, if anything, to
        do with these values.

        Uses ``_raw_conn`` (not the psycopg-compat ``_conn``) because
        ``PsycopgCompatConnection`` strips ``RETURNING`` down to a single
        column via regex (see ``sqlite_compat.py``) — this query needs four.
        """
        row = self._raw_conn.execute(
            "UPDATE memories SET replay_count = replay_count + 1 WHERE id = ? "
            "RETURNING replay_count, hippocampal_dependency, "
            "schema_match_score, importance",
            (memory_id,),
        ).fetchone()
        self._raw_conn.commit()
        return dict(row) if row else None

    def update_memory_hippocampal_dependency(
        self, memory_id: int, dependency: float
    ) -> None:
        """Persist a new hippocampal_dependency value. No policy — pure write."""
        self._conn.execute(
            "UPDATE memories SET hippocampal_dependency = ? WHERE id = ?",
            (dependency, memory_id),
        )
        self._conn.commit()

    # ── Oscillatory State ─────────────────────────────────────────────

    def save_oscillatory_state(self, state_json: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO oscillatory_state (id, state_json) VALUES (1, ?)",
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
            "SELECT id, heat_base, importance, "
            "consolidation_stage, directory_context, interference_score "
            "FROM memories WHERE domain = ? "
            "AND NOT is_stale ORDER BY heat_base DESC LIMIT ?",
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
        """CLS input — mirror of PgStatsMixin.get_episodic_memories. Reads
        current_memories so a superseded episodic version is never
        crystallized into a durable semantic fact.
        """
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
            f"SELECT * FROM current_memories WHERE {where} "
            "ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_semantic_memories(
        self, domain: str = "", limit: int = 500
    ) -> list[dict[str, Any]]:
        """CLS dedup input — mirror of PgStatsMixin.get_semantic_memories.
        Reads current_memories so a superseded semantic row cannot suppress
        the corrected abstraction.
        """
        if domain:
            rows = self._conn.execute(
                "SELECT * FROM current_memories WHERE store_type = 'semantic' "
                "AND domain = ? AND NOT is_stale "
                "ORDER BY created_at DESC LIMIT ?",
                (domain, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM current_memories WHERE store_type = 'semantic' "
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
            "SELECT timestamp FROM consolidation_log ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return row["timestamp"] if row else None

    def count_active_triggers(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS c FROM prospective_memories WHERE is_active"
        ).fetchone()
        return row["c"] if row else 0
