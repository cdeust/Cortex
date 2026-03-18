"""Handler: memory_stats — memory system diagnostics.

Returns aggregate statistics about the memory system state:
counts, heat distribution, entity/relationship counts, trigger status.
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "description": "Memory system diagnostics: counts, heat distribution, entities, triggers.",
    "inputSchema": {
        "type": "object",
        "properties": {},
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
