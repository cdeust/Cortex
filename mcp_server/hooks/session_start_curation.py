"""SessionStart hook curator signals: pending wiki clusters, grooming staleness.

source: ADR-0498"""

from __future__ import annotations

from mcp_server.hooks.session_start_common import _log


def _count_pending_curations(conn) -> int:
    """Count topic clusters of PG memories that warrant a wiki page
        but don't have one yet.

        Surfaced in the SessionStart preamble so the in-session LLM
        (Opus 4.7) sees how much authoring work is queued. The full
        detection logic lives in ``mcp_server.core.auto_curator``; this
        helper just pulls a sample of recently-accessed memories and asks
        the curator to count.

    source: ADR-0498"""
    try:
        from mcp_server.core.auto_curator import count_pending_clusters  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

        # `effective_heat` is a PL/pgSQL function, not a column —
        # mirror the form used in _fetch_hot_memories above. Without
        # the (m, NOW()) call form, Postgres rejects with
        # `column "effective_heat" does not exist` and the schema
        # integrity test catches it.
        rows = conn.execute(
            "SELECT m.id, m.content, m.tags, "
            "effective_heat(m, NOW()) AS effective_heat, "
            "m.created_at, m.domain "
            "FROM memories m JOIN current_memories cm ON cm.id = m.id "
            "WHERE NOT m.is_stale "
            "ORDER BY m.last_accessed DESC NULLS LAST, m.created_at DESC "
            "LIMIT 500"
        ).fetchall()
        memories: list[dict] = []
        for r in rows:
            d = dict(r) if not isinstance(r, dict) else r
            memories.append(
                {
                    "id": d.get("id"),
                    "content": d.get("content") or "",
                    "tags": list(d.get("tags") or []),
                    "effective_heat": float(d.get("effective_heat") or 0.0),
                    "created_at": str(d.get("created_at") or ""),
                    "domain": d.get("domain") or "",
                }
            )
        if not memories:
            return 0
        # source: ADR-0498
        try:
            from mcp_server.infrastructure.config import WIKI_ROOT  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
            from mcp_server.infrastructure.wiki_page_fs import (  # noqa: PLC0415 — same optional-feature probe boundary
                build_wiki_page_port,
            )

            wiki_page_port = build_wiki_page_port(str(WIKI_ROOT))
        except ImportError:
            wiki_page_port = None
        return count_pending_clusters(memories, wiki_root=wiki_page_port)
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"pending-cluster count failed (non-fatal): {exc}")
        return 0


def _fetch_grooming_staleness(conn) -> list[str]:
    """Return the kinds ('wiki'/'distillation'/'promotion') of
        judgment-level grooming that are overdue for attention.

        Precondition: none.
        Postcondition: returns a subset of {'wiki', 'distillation',
        'promotion'} -- kinds whose last execution is older than
        ``core.grooming_health.GROOMING_STALENESS_THRESHOLD_DAYS`` days, or
        that have never executed. Read-only, three bounded aggregate
        queries (~30ms combined, EXPLAIN ANALYZE 2026-07-11 -- see
        ``PgStatsMixin.get_grooming_ages`` for the per-query cost
        breakdown; this hook queries directly rather than going through
        ``get_shared_store`` to avoid pulling the full store composition
        into the SessionStart hot path). Deliberately does NOT call the
        backlog-count planners (curate_wiki/curate_distill/
        lesson_promotion) -- those cost ~1s combined
        (get_grooming_health.py), too expensive for every session start.

    source: ADR-0498"""
    try:
        from mcp_server.core.grooming_health import is_stale  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

        row = conn.execute(
            # source: docs/verification/codex-session-start-query-20261002.md
            # Materialize the indexed lesson subset before MAX: otherwise the
            # planner scans the created_at index backwards for absent prefixes.
            "WITH lessons AS MATERIALIZED ("
            "  SELECT created_at, tags FROM memories "
            "  WHERE tags @> '[\"lesson\"]'::jsonb) "
            "SELECT "
            "  (SELECT MAX(tended) FROM wiki.pages) AS wiki_last, "
            "  (SELECT MAX(created_at) FROM lessons m "
            "     WHERE EXISTS (SELECT 1 FROM jsonb_array_elements_text(m.tags) tg "
            "                   WHERE tg LIKE 'distill-of:%')) AS distill_last, "
            "  (SELECT MAX(created_at) FROM lessons m "
            "     WHERE EXISTS (SELECT 1 FROM jsonb_array_elements_text(m.tags) tg "
            "                   WHERE tg LIKE 'promoted:%')) AS promo_last"
        ).fetchone()
        if not row:
            return []
        d = dict(row) if not isinstance(row, dict) else row
        stale = []
        for kind, col in (
            ("wiki", "wiki_last"),
            ("distillation", "distill_last"),
            ("promotion", "promo_last"),
        ):
            ts = d.get(col)
            last_iso = ts.isoformat() if ts else None
            if is_stale(last_iso):
                stale.append(kind)
        return stale
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"grooming-staleness fetch failed (non-fatal): {exc}")
        return []
