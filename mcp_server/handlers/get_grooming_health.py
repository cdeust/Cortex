"""Handler: get_grooming_health — backlog + staleness for judgment-level
grooming (wiki authoring, lesson distillation, lesson promotion).

source: ADR-0394"""

from __future__ import annotations

from typing import Any

from mcp_server.core.grooming_health import (
    GROOMING_STALENESS_THRESHOLD_DAYS,
    days_since,
    is_stale,
)
from mcp_server.handlers._tool_meta import READ_ONLY
from mcp_server.infrastructure.memory_store import get_shared_store
from mcp_server.infrastructure.pg_store_lesson_promotion import (
    count_lesson_promotion_candidates,
)
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from mcp_server.infrastructure.sqlite_store_lesson_promotion import (
    count_lesson_promotion_candidates as count_promotion_candidates_sqlite,
)
from mcp_server.handlers import curate_distill, curate_wiki

schema = {
    "title": "Grooming health (backlog + staleness)",
    "annotations": READ_ONLY,
    "outputSchema": {
        "type": "object",
        "required": ["kinds", "threshold_days"],
        "properties": {
            "kinds": {
                "type": "object",
                "description": (
                    "Per-kind status keyed 'wiki'/'distillation'/"
                    "'promotion': {backlog_count, last_run_at, "
                    "days_since_last_run, stale}."
                ),
            },
            "threshold_days": {
                "type": "number",
                "description": (
                    "Alert threshold in days, sourced from measured "
                    "session cadence (mcp_server.core.grooming_health "
                    "module docstring documents the exact query)."
                ),
            },
            "any_stale": {
                "type": "boolean",
                "description": "True if any kind exceeds threshold_days.",
            },
        },
    },
    "description": (
        "Backlog size and staleness age for the three judgment-level "
        "grooming planners (curate_wiki, curate_distill, "
        "lesson_promotion) — distinct from `consolidate`'s mechanical "
        "wiki maintenance (purge/backfill/dashboards, which already "
        "self-reports and needs no staleness alarm). For each kind, "
        "returns the exact eligible-backlog count and how long ago that "
        "kind of grooming last actually executed (None = never). "
        "`stale=true` when a kind has gone longer than `threshold_days` "
        "(sourced from measured session cadence, see "
        "core.grooming_health) without running, or has never run at "
        "all. Read-only. Latency ~1s (curate_distill + curate_wiki are "
        "themselves bounded-scan planners, not indexed aggregates — this "
        "tool is meant for explicit on-demand health checks, not the "
        "SessionStart hot path)."
    ),
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
}


def _count_promotion_candidates(store: Any) -> int:
    """Backend dispatch for the promotion backlog count.

    source: ADR-0394"""
    if isinstance(store, SqliteMemoryStore):
        return count_promotion_candidates_sqlite(store._conn)
    return count_lesson_promotion_candidates(store._conn)


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Aggregate backlog counts + staleness ages for the three grooming kinds.

    Precondition: none.
    Postcondition: read-only — this handler never calls remember,
    wiki_write, add_rule, create_trigger, or any store mutation. Each
    kind's stale flag is computed by ``core.grooming_health.is_stale``
    against the shared, sourced threshold.
    """

    store = get_shared_store()
    ages = store.get_grooming_ages()

    distill_result = await curate_distill.handler({"limit": 1})
    wiki_result = await curate_wiki.handler(
        {"limit": 1, "coverage_jobs_max": 0, "reauthor_jobs_max": 0}
    )
    promotion_count = _count_promotion_candidates(store)

    kinds: dict[str, Any] = {}
    for kind, backlog_count, last_run_at in (
        ("wiki", wiki_result.get("total_clusters_eligible", 0), ages["wiki"]),
        (
            "distillation",
            distill_result.get("total_dossiers_eligible", 0),
            ages["distillation"],
        ),
        ("promotion", promotion_count, ages["promotion"]),
    ):
        kinds[kind] = {
            "backlog_count": backlog_count,
            "last_run_at": last_run_at,
            "days_since_last_run": (
                round(d, 2) if (d := days_since(last_run_at)) is not None else None
            ),
            "stale": is_stale(last_run_at),
        }

    return {
        "kinds": kinds,
        "threshold_days": GROOMING_STALENESS_THRESHOLD_DAYS,
        "any_stale": any(k["stale"] for k in kinds.values()),
    }
