"""Heat / homeostatic-factor mixin for PgMemoryStore.

Split out of pg_store.py (issue: 1384-line file over the 300-line §4.1
cap) — the A3 canonical heat_base writers (``bump_heat_raw``,
``update_memories_heat_batch``) and the per-(domain, write_class)
homeostatic-factor read/write pair live together: both are the
"how much does this memory's heat matter right now" concern.
"""

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

    def update_memory_heat(self, memory_id: int, heat: float) -> None:
        """Canonical A3 single-row heat writer. Delegates to bump_heat_raw.

        Retained as a thin adapter so existing call sites don't need to
        know about heat_base_set_at; the heat value semantics are
        preserved because bump_heat_raw writes heat_base + stamps the
        bump timestamp.
        Source: docs/program/phase-3-a3-migration-design.md §3.1.
        """
        self.bump_heat_raw(memory_id, heat)

    def bump_heat_raw(self, memory_id: int, new_heat_base: float) -> None:
        """A3 canonical single writer on `memories.heat_base` (invariant I2).

        Writes heat_base AND refreshes heat_base_set_at so subsequent
        effective_heat() reads compute decay from the bump timestamp,
        not the row's previous anchor. Clamped to [0, 1] defensively —
        the CHECK constraint enforces the same bound but a defensive
        clamp avoids IntegrityError round-trips for callers computing
        near-limit values.

        Source: docs/program/phase-3-a3-migration-design.md §3.1.
        Post-A3 this is the ONE canonical site that writes heat_base;
        all other writers (anchor, preemptive_context, citation bump)
        route through here.
        """
        clamped = max(0.0, min(1.0, float(new_heat_base)))
        self._execute(
            "UPDATE memories SET heat_base = %s, heat_base_set_at = NOW() "
            "WHERE id = %s",
            (clamped, memory_id),
        )
        self._conn.commit()

    def get_homeostatic_factor(self, domain: str, write_class: str = "auto") -> float:
        """A3: fetch per-(domain, write_class) homeostatic factor, default 1.0.

        Readers MUST use this helper rather than querying the table
        directly — new domains arrive between homeostatic runs and have
        no row. The COALESCE-to-1.0 default preserves neutral scaling.

        M-D3 (7.1, stratification): ``homeostatic_state``'s primary key is
        ``(domain, write_class)`` — one row per class, not one per domain.
        ``write_class`` defaults to ``"auto"`` because that is the only
        class the recall-path read query (``pg_schema.py::recall_memories``
        / ``fetch_member_stats`` / the reheat + dedup probes) ever
        resolves; every other caller of this method (currently only
        ``handlers/consolidation/homeostatic.py``) passes its class
        explicitly. See ``mcp_server.core.write_class`` for the taxonomy
        this parameter is drawn from.

        Source: docs/program/phase-3-a3-migration-design.md §5.
        """
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

        Replaces the per-row heat UPDATE pattern in the homeostatic cycle
        — one row written per cycle instead of 66K. Clamped to the
        CHECK bounds (0 < factor < 10). See ``get_homeostatic_factor`` for
        the M-D3 ``write_class`` rationale.
        """
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

        The 2026-07-10 19:22 fold that re-suppressed the deliberate class
        left no queryable trace anywhere except the row-level signature on
        ``memories`` itself (``heat_base_set_at`` matching a batched
        write) — confirmed by direct SQL, not by this table, because this
        table did not exist yet. Every fold from this point forward is
        DB-queryable without reconstructing it from row timestamps.
        """
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

        Source: issue #13 (darval); docs/program/phase-3-a3-migration-design.md §3.2.
        """
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
