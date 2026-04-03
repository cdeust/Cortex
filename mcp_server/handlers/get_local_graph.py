"""Handler: get_local_graph — fetch a memory's local neighborhood for navigation.

Composition root wiring pg_store_navigation.get_local_graph() to
core/local_graph.build_local_graph(). Returns a typed graph structure
with center, entity, and neighbor nodes plus edges.

Used by the Obsidian-like navigation UI to render a mini force-directed
graph centered on a selected memory.
"""

from __future__ import annotations

from typing import Any

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "description": "Get a memory's local graph neighborhood — entities, backlinked memories, and relationships. For Obsidian-like navigation.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "integer",
                "description": "Center memory ID to expand from",
            },
            "depth": {
                "type": "integer",
                "description": "Entity hops (1 = direct neighbors, 2 = friends-of-friends). Default 1.",
            },
            "max_neighbors": {
                "type": "integer",
                "description": "Maximum neighbor memories to return (default 30)",
            },
        },
        "required": ["memory_id"],
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
    """Fetch and build the local graph for a memory."""
    args = args or {}

    memory_id = args.get("memory_id")
    if memory_id is None:
        return {"error": "memory_id is required"}

    memory_id = int(memory_id)
    depth = min(int(args.get("depth", 1)), 3)
    max_neighbors = min(int(args.get("max_neighbors", 30)), 100)

    store = _get_store()
    raw = store.get_local_graph(memory_id, depth=depth, max_neighbors=max_neighbors)

    if raw["center"] is None:
        return {"error": f"Memory {memory_id} not found"}

    from mcp_server.core.local_graph import build_local_graph

    return build_local_graph(
        raw["center"],
        raw["entities"],
        raw["neighbors"],
        raw["relationships"],
    )
