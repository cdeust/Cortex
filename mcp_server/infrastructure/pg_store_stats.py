"""Stats, diagnostics, consolidation, oscillatory state mixin for PgMemoryStore."""

from __future__ import annotations

from mcp_server.infrastructure.pg_store_host import PgStoreHost

from typing import TYPE_CHECKING, Any

import psycopg

if TYPE_CHECKING:
    import psycopg


class PgStatsMixin(PgStoreHost):
    """Diagnostics, consolidation stages, CLS queries on PostgreSQL."""

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
            row = self._execute(
                "SELECT COUNT(*) AS c, "
                "EXTRACT(EPOCH FROM (NOW() - MAX("
                "COALESCE(last_accessed, created_at)))) / 3600.0 AS hours "
                "FROM memories WHERE stimulus_signature = %s",
                (signature,),
            ).fetchone()
        except psycopg.Error:
            return 0, None
        if not row or not row["c"]:
            return 0, None
        hours = row["hours"]
        return int(row["c"]), (float(hours) if hours is not None else None)

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
            row = self._execute(
                "SELECT COUNT(*) AS c FROM memories "
                "WHERE extinction_strength >= %s AND NOT is_stale",
                (threshold,),
            ).fetchone()
        except psycopg.Error:
            return 0
        if not row or not row["c"]:
            return 0
        return int(row["c"])

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
        self, limit: int = 20, min_access_count: int = 1, heads_only: bool = False
    ) -> list[dict[str, Any]]:
        """Shared primitive with mixed callers. heads_only routes the read
        through the current_memories view (supersession chain heads only):
        content-serving callers (navigate_memory SR graph, curate_wiki,
        auto_task_record_writer) pass True.
        """
        src = "current_memories" if heads_only else "memories"
        rows = self._execute(
            f"SELECT * FROM {src} WHERE access_count >= %s "  # noqa: S608 — identifier is the two-literal in-code ternary memories/current_memories; values are bound parameters (docs/ASSURANCE-CASE.md §5)
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
        ).one()
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

    # ── Grooming staleness (judgment-level curation, not the mechanical
    # consolidate pass -- see core.grooming_health module docstring) ────

    def get_grooming_ages(self) -> dict[str, str | None]:
        """Last-executed timestamp for each judgment-level grooming kind.

        Precondition: none.
        Postcondition: returns {"wiki", "distillation", "promotion"} ->
        ISO-8601 timestamp of the most recent judgment-level action of
        that kind, or None if that kind has never executed in this
        store. Read-only, three bounded aggregate queries:
          - wiki: MAX(wiki.pages.tended) -- ~0.4ms at 154 rows (EXPLAIN
            ANALYZE, 2026-07-11; no dedicated index needed at this
            table size, sequential scan).
          - distillation / promotion: filtered by the 'lesson' tag
            (semantically required -- curate_distill.py and
            lesson_promotion.py both only ever tag their output
            'lesson', so this prefilter cannot exclude a true positive)
            then a tag-prefix scan for 'distill-of:'/'promoted:'.
            idx_memories_tags_gin makes the 'lesson' prefilter an index
            scan; measured 18-23ms worst case (zero matching rows --
            the only state observed so far, 2026-07-11), collapsing to
            sub-ms once any row matches.
        """
        wiki_row = self._execute(
            "SELECT MAX(tended) AS last_ts FROM wiki.pages"
        ).fetchone()
        wiki_last = (
            wiki_row["last_ts"].isoformat()
            if wiki_row and wiki_row["last_ts"]
            else None
        )

        distill_row = self._execute(
            "SELECT MAX(created_at) AS last_ts FROM memories m "
            "WHERE m.tags @> '[\"lesson\"]'::jsonb "
            "AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(m.tags) tg "
            "WHERE tg LIKE 'distill-of:%')"
        ).fetchone()
        distill_last = (
            distill_row["last_ts"].isoformat()
            if distill_row and distill_row["last_ts"]
            else None
        )

        promo_row = self._execute(
            "SELECT MAX(created_at) AS last_ts FROM memories m "
            "WHERE m.tags @> '[\"lesson\"]'::jsonb "
            "AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(m.tags) tg "
            "WHERE tg LIKE 'promoted:%')"
        ).fetchone()
        promo_last = (
            promo_row["last_ts"].isoformat()
            if promo_row and promo_row["last_ts"]
            else None
        )

        return {
            "wiki": wiki_last,
            "distillation": distill_last,
            "promotion": promo_last,
        }
