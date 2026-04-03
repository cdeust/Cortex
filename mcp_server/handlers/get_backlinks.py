"""Handler: get_backlinks — list memories linked to an entity.

Composition root wiring pg_store_navigation.get_backlinks() to
core/backlink_resolver.resolve_backlinks(). Returns memories grouped
by domain with relevance scoring.

Used by the Obsidian-like navigation UI to show which memories
reference a given entity.
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "description": "Get all memories linked to an entity (backlinks), grouped by domain and ranked by relevance.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "integer",
                "description": "Entity ID to get backlinks for",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum memories to return (default 50)",
            },
        },
        "required": ["entity_id"],
    },
}

# ── Singleton ─────────────────────────────────────────────────────────────

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        settings = get_memory_settings()
        _store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
    return _store


# ── Handler ───────────────────────────────────────────────────────────────


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fetch and resolve backlinks for an entity."""
    args = args or {}

    entity_id = args.get("entity_id")
    if entity_id is None:
        return {"error": "entity_id is required"}

    entity_id = int(entity_id)
    limit = min(int(args.get("limit", 50)), 200)

    store = _get_store()
    raw = store.get_backlinks(entity_id, limit=limit)

    from mcp_server.core.backlink_resolver import resolve_backlinks

    return resolve_backlinks(raw)
