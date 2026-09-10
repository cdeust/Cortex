"""Heat / homeostatic-factor mixin for PgMemoryStore.

source: ADR-0549"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.pg_store_host import PgStoreHost


class PgHeatMixin(PgStoreHost):
    """A3 heat_base writers + homeostatic factor + fold telemetry."""

    def get_memory(self, memory_id: int) -> dict[str, Any] | None:
        row = self._execute(
            "SELECT * FROM memories WHERE id = %s", (memory_id,)
        ).fetchone()
        if row is None:
            return None
        return self._normalize_memory_row(row)

    def get_memories_by_ids(self, memory_ids: list[int]) -> dict[int, dict[str, Any]]:
        """Fetch memory rows for the supplied IDs. Missing IDs are omitted;
        callers replay
        their own order and duplicates.

                source: ADR-0549"""
        if not memory_ids:
            return {}
        rows = self._execute(
            "SELECT * FROM memories WHERE id = ANY(%s::int[])",
            (memory_ids,),
        ).fetchall()
        return {row["id"]: self._normalize_memory_row(row) for row in rows}

    def update_memory_heat(self, memory_id: int, heat: float) -> None:
        """Canonical A3 single-row heat writer. Delegates to bump_heat_raw.

        source: ADR-0549"""
        self.bump_heat_raw(memory_id, heat)

    def bump_heat_raw(self, memory_id: int, new_heat_base: float) -> None:
        """A3 canonical single writer on `memories.heat_base`.

        source: ADR-0549"""
        clamped = max(0.0, min(1.0, float(new_heat_base)))
        self._execute(
            "UPDATE memories SET heat_base = %s, heat_base_set_at = NOW() "
            "WHERE id = %s",
            (clamped, memory_id),
        )
        self._conn.commit()

    def get_homeostatic_factor(self, domain: str, write_class: str = "auto") -> float:
        """A3: fetch per-(domain, write_class) homeostatic factor, default 1.0.

        source: ADR-0549"""
        row = self._execute(
            "SELECT COALESCE(MAX(factor), 1.0)::REAL AS factor "
            "FROM homeostatic_state WHERE domain = %s AND write_class = %s",
            (domain or "", write_class),
        ).fetchone()
        if row is None:
            return 1.0
        try:
            return float(row["factor"])
        except (KeyError, TypeError):
            return 1.0

    def set_homeostatic_factor(
        self, domain: str, factor: float, write_class: str = "auto"
    ) -> None:
        """A3: upsert per-(domain, write_class) homeostatic factor.

        source: ADR-0549"""
        clamped = max(0.01, min(9.99, float(factor)))
        self._execute(
            "INSERT INTO homeostatic_state (domain, write_class, factor, updated_at) "
            "VALUES (%s, %s, %s, NOW()) "
            "ON CONFLICT (domain, write_class) DO UPDATE "
            "SET factor = EXCLUDED.factor, updated_at = NOW()",
            (domain or "", write_class, clamped),
        )
        self._conn.commit()

    def log_homeostatic_fold(
        self,
        domain: str,
        write_class: str,
        factor: float,
        rows_folded: int,
    ) -> int:
        """M-D3 (7.1): journal a fold event — the telemetry step 1 asked for.

        source: ADR-0549"""
        row = self._execute(
            "INSERT INTO homeostatic_fold_log "
            "(domain, write_class, factor, rows_folded) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (domain or "", write_class, float(factor), int(rows_folded)),
        ).fetchone()
        self._conn.commit()
        return row["id"] if row else 0

    def update_memories_heat_batch(self, updates: list[tuple[int, float]]) -> int:
        """A3 batch heat writer. Writes heat_base + refreshes heat_base_set_at.

                Single ``UPDATE ... FROM UNNEST()`` statement so 60k+ updates
                become one round-trip and one commit. The homeostatic cohort
                branch is the main consumer post-A3 (decay is lazy). Returns
                the number of rows written.

        source: ADR-0549"""
        if not updates:
            return 0
        ids = [int(u[0]) for u in updates]
        heats = [max(0.0, min(1.0, float(u[1]))) for u in updates]
        self._execute(
            "UPDATE memories AS m "
            "SET heat_base = v.new_heat_base, heat_base_set_at = NOW() "
            "FROM (SELECT UNNEST(%s::int[]) AS id, "
            "            UNNEST(%s::real[]) AS new_heat_base) AS v "
            "WHERE m.id = v.id",
            (ids, heats),
        )
        self._conn.commit()
        return len(updates)
