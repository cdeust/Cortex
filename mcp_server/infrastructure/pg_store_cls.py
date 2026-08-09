"""CLS / oscillatory-state / interference mixin for PgMemoryStore.

Split out of pg_store_stats.py (issue #407: 406 lines over the
300-line §4.1 cap) — episodic/semantic CLS reads (McClelland 1995),
theta/gamma oscillatory-clock singleton state (Hasselmo 2005), and
interference detection (proactive/retroactive) are grouped here as the
"consolidation-adjacent read/write signals" concern, distinct from
cascade stage transitions (``pg_store_consolidation_stage``) and plain
counts/dashboard (``pg_store_stats``).
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.pg_store_host import PgStoreHost


class PgClsMixin(PgStoreHost):
    """CLS queries + oscillatory state + interference on PostgreSQL."""

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
        """CLS input. Reads current_memories: the CLS clusters EVERY returned
        row (NOT is_stale does not cover supersession), so a superseded
        episodic version would be crystallized into a durable semantic fact.
        Chain heads carry the correction — consolidating heads only is the
        contract.
        """
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
            f"SELECT * FROM current_memories WHERE {where} "  # noqa: S608 — WHERE built from in-code literal fragments; values are bound parameters (docs/ASSURANCE-CASE.md §5)
            "ORDER BY created_at DESC LIMIT %s",
            params,
        ).fetchall()
        return [self._normalize_memory_row(r) for r in rows]

    def get_semantic_memories(
        self, domain: str = "", limit: int = 500
    ) -> list[dict[str, Any]]:
        """CLS dedup input. Reads current_memories: a superseded semantic row
        matching >0.85 cosine would otherwise suppress the creation of the
        corrected abstraction.
        """
        if domain:
            rows = self._execute(
                "SELECT * FROM current_memories WHERE store_type = 'semantic' "
                "AND domain = %s AND NOT is_stale "
                "ORDER BY created_at DESC LIMIT %s",
                (domain, limit),
            ).fetchall()
        else:
            rows = self._execute(
                "SELECT * FROM current_memories WHERE store_type = 'semantic' "
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
