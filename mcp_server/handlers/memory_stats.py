"""Handler: memory_stats — memory system diagnostics.

Returns aggregate statistics about the memory system state:
counts, heat distribution, entity/relationship counts, trigger status.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.grooming_health import (
    GROOMING_STALENESS_THRESHOLD_DAYS,
    days_since,
    is_stale,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
from mcp_server.handlers import abandoned_work
from mcp_server.handlers._tool_meta import READ_ONLY
from mcp_server.handlers._telemetry_wrap import instrument

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "title": "Memory stats",
    "annotations": READ_ONLY,
    "description": (
        "Aggregate population diagnostics for the memory system: "
        "total / episodic / semantic / active / archived / stale / "
        "protected memory counts, average heat, entity and relationship "
        "totals, active prospective triggers, last consolidation "
        "timestamp, and vector-search availability (pgvector). Use this "
        "for health checks, dashboards, or before/after a `consolidate` "
        "run to verify cycles fired. Distinct from `assess_coverage` "
        "(scored 0-100 with recommendations, this is raw counts), "
        "`detect_gaps` (enumerates specific missing things), and "
        "`list_domains` (per-domain profile rows, not memory counts). "
        "Read-only. Takes no arguments. Latency ~75ms (includes the "
        "grooming-staleness ages below). Returns "
        "{total_memories, episodic_count, semantic_count, active_count, "
        "archived_count, stale_count, protected_count, avg_heat, "
        "total_entities, total_relationships, active_triggers, "
        "last_consolidation, has_vector_search, grooming_staleness, "
        "abandoned_workers}. "
        "`grooming_staleness` carries last-run age (days) for the three "
        "judgment-level grooming kinds (wiki/distillation/promotion) "
        "against a sourced threshold -- ages only, no backlog counts "
        "(those cost ~1s combined; call `get_grooming_health` for the "
        "full picture). `abandoned_workers` reports, per tool, the workers "
        "of this server process still running after their caller was "
        "cancelled (`in_flight`) and how abandoned workers ended since the "
        "process started (`ended`: completed / raised / cancelled): an "
        "abandoned mutating call that completed applied its writes although "
        "its caller never received the result."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {},
        "additionalProperties": False,
    },
}

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


async def _handler_impl(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return memory system statistics."""
    store = _get_store()

    counts = store.count_memories()
    avg_heat = store.get_avg_heat()
    entity_count = store.count_entities()
    rel_count = store.count_relationships()
    trigger_count = store.count_active_triggers()
    last_consolidation = store.get_last_consolidation()
    grooming_ages = store.get_grooming_ages()
    grooming_staleness = {
        kind: {
            "last_run_at": last_run_at,
            "days_since_last_run": (
                round(d, 2) if (d := days_since(last_run_at)) is not None else None
            ),
            "stale": is_stale(last_run_at),
        }
        for kind, last_run_at in grooming_ages.items()
    }

    return {
        "total_memories": counts.get("total", 0),
        "episodic_count": counts.get("episodic", 0),
        "semantic_count": counts.get("semantic", 0),
        "active_count": counts.get("active", 0),
        "archived_count": counts.get("archived", 0),
        "stale_count": counts.get("stale", 0),
        "protected_count": counts.get("protected", 0),
        "avg_heat": round(avg_heat, 4),
        "total_entities": entity_count,
        "total_relationships": rel_count,
        "active_triggers": trigger_count,
        "last_consolidation": last_consolidation,
        "has_vector_search": store.has_vec,
        "grooming_staleness": grooming_staleness,
        "grooming_staleness_threshold_days": GROOMING_STALENESS_THRESHOLD_DAYS,
        "abandoned_workers": abandoned_work.snapshot(),
    }


handler = instrument("memory_stats", _handler_impl, result_count_key=None)
