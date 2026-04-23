"""Handler: memory_stats — memory system diagnostics.

Returns aggregate statistics about the memory system state:
counts, heat distribution, entity/relationship counts, trigger status.
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.handlers._tool_meta import READ_ONLY

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
        "Read-only. Takes no arguments. Latency ~50ms. Returns "
        "{total_memories, episodic_count, semantic_count, active_count, "
        "archived_count, stale_count, protected_count, avg_heat, "
        "total_entities, total_relationships, active_triggers, "
        "last_consolidation, has_vector_search}."
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
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return memory system statistics."""
    store = _get_store()

    counts = store.count_memories()
    avg_heat = store.get_avg_heat()
    entity_count = store.count_entities()
    rel_count = store.count_relationships()
    trigger_count = store.count_active_triggers()
    last_consolidation = store.get_last_consolidation()

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
    }
