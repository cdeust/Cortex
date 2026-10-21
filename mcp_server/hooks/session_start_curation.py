"""SessionStart hook curator signals: pending wiki clusters, grooming staleness.

source: ADR-0498"""

from __future__ import annotations

from mcp_server.hooks.session_start_common import _log
from mcp_server.infrastructure.hook_queries import (
    session_curation_sample,
    session_grooming_ages,
)

# source: ADR-0498
_GROOMING_COLUMNS = (
    ("wiki", "wiki_last"),
    ("distillation", "distill_last"),
    ("promotion", "promo_last"),
)


def _curator_memory(r) -> dict:
    """One sampled row in the shape ``count_pending_clusters`` reads."""
    d = dict(r) if not isinstance(r, dict) else r
    return {
        "id": d.get("id"),
        "content": d.get("content") or "",
        "tags": list(d.get("tags") or []),
        "effective_heat": float(d.get("effective_heat") or 0.0),
        "created_at": str(d.get("created_at") or ""),
        "domain": d.get("domain") or "",
    }


def _wiki_page_port():
    """The wiki page port the curator checks pages against, or None.

    source: ADR-0498"""
    try:
        from mcp_server.infrastructure.config import WIKI_ROOT  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
        from mcp_server.infrastructure.wiki_page_fs import (  # noqa: PLC0415 — same optional-feature probe boundary
            build_wiki_page_port,
        )

        return build_wiki_page_port(str(WIKI_ROOT))
    except ImportError:
        return None


def _count_pending_curations(store) -> int:
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

        rows = store.call(session_curation_sample)
        memories = [_curator_memory(r) for r in rows]
        if not memories:
            return 0
        return count_pending_clusters(memories, wiki_root=_wiki_page_port())
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"pending-cluster count failed (non-fatal): {exc}")
        return 0


def _fetch_grooming_staleness(store) -> list[str]:
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

        row = store.call(session_grooming_ages)
        if not row:
            return []
        d = dict(row) if not isinstance(row, dict) else row
        return [
            kind
            for kind, col in _GROOMING_COLUMNS
            if is_stale(d[col].isoformat() if d.get(col) else None)
        ]
    except Exception as exc:  # noqa: BLE001 — hook boundary; failure is logged to the hook log, the banner degrades
        _log(f"grooming-staleness fetch failed (non-fatal): {exc}")
        return []
