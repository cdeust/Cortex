"""Diagnostics/dashboard/grooming-staleness mixin for PgMemoryStore.

Cascade stage transitions live in the sibling ``pg_store_consolidation_stage``
module and CLS/oscillatory/interference queries in ``pg_store_cls`` (both
split out by issue #407: this file was 406 lines over the 300-line §4.1 cap).
"""

from __future__ import annotations

from typing import Any

import psycopg

from mcp_server.infrastructure.pg_store_host import PgStoreHost


class PgStatsMixin(PgStoreHost):
    """Diagnostics, dashboard reads, and grooming staleness on PostgreSQL."""

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

    def count_active_triggers(self) -> int:
        row = self._execute(
            "SELECT COUNT(*) AS c FROM prospective_memories WHERE is_active"
        ).fetchone()
        return row["c"] if row else 0

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
