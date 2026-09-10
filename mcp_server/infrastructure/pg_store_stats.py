"""Diagnostics/dashboard/grooming-staleness mixin for PgMemoryStore.

source: ADR-0569"""

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
        """Return (repeat_count, hours_since_last) for the normalized stimulus
        signature.
        hours_since_last is None for an unseen signature. Returns (0, None) on error or
        when the signature column is absent.

                source: ADR-0569"""
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
        """Return the count of rows with extinction_strength at or above
        threshold. Returns
        0 on errors or when the column is absent. Rows are not modified.

                source: ADR-0569"""
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

    def _grooming_tag_prefix_age(self, prefix: str) -> str | None:
        """MAX(created_at) among 'lesson'-tagged memories whose tags also
                carry a ``prefix``-prefixed entry (e.g. 'distill-of:', 'promoted:').

        source: ADR-0569"""
        row = self._execute(
            "SELECT MAX(created_at) AS last_ts FROM memories m "
            "WHERE m.tags @> '[\"lesson\"]'::jsonb "
            "AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(m.tags) tg "
            "WHERE tg LIKE %s)",
            (f"{prefix}%",),
        ).fetchone()
        return row["last_ts"].isoformat() if row and row["last_ts"] else None

    def get_grooming_ages(self) -> dict[str, str | None]:
        """Last-executed timestamp for each judgment-level grooming kind.

        Precondition: none. Postcondition: returns {"wiki", "distillation", "promotion"}
        ->
                ISO-8601 timestamp of the most recent judgment-level action of
                that kind, or None if that kind has never executed in this
                store. Read-only. wiki: MAX(wiki.pages.tended) -- ~0.4ms at 154
                rows (EXPLAIN ANALYZE, 2026-07-11; no dedicated index needed at
                this table size, sequential scan). distillation/promotion: see
                ``_grooming_tag_prefix_age``.

        source: ADR-0569"""
        wiki_row = self._execute(
            "SELECT MAX(tended) AS last_ts FROM wiki.pages"
        ).fetchone()
        wiki_last = (
            wiki_row["last_ts"].isoformat()
            if wiki_row and wiki_row["last_ts"]
            else None
        )
        return {
            "wiki": wiki_last,
            "distillation": self._grooming_tag_prefix_age("distill-of:"),
            "promotion": self._grooming_tag_prefix_age("promoted:"),
        }
