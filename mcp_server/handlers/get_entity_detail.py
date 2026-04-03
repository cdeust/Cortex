"""Handler: get_entity_detail — fetch a full entity profile for navigation.

Composition root: wires infrastructure (pg_store) to core (entity_profile)
to produce a navigable entity detail view with stats, top memories,
related entities, and temporal span.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.entity_profile import build_entity_profile
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore


_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fetch a full entity profile by entity_id.

    Args (via args dict):
        entity_id: int — required, the entity to look up.

    Returns:
        Entity profile dict or error.
    """
    if not args or args.get("entity_id") is None:
        return {"error": "entity_id is required"}

    entity_id = int(args["entity_id"])
    store = _get_store()

    entity = store.get_entity_by_id(entity_id)
    if entity is None:
        return {"error": "entity_not_found", "entity_id": entity_id}

    entity_name = entity.get("name", "")
    memories = store.get_memories_mentioning_entity(entity_name, limit=50)
    relationships = store.get_relationships_for_entity(entity_id, direction="both")

    profile = build_entity_profile(entity, memories, relationships)
    return {"entity": profile}
