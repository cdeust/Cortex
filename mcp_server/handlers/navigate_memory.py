"""Handler: navigate_memory — SR-based memory space traversal.

Treats the memory store as a navigable space where memories are linked
by temporal co-access (Successor Representation). Starting from a given
memory, this tool explores the neighborhood: what memories tend to be
accessed alongside or after this one?

Useful for: following a thread of thinking, exploring a topic cluster,
discovering latent associations between memories.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.cognitive_map import (
    build_temporal_co_access,
    navigate_from,
    project_to_2d,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "description": "Navigate memory space using Successor Representation (co-access patterns). Starting from a memory ID, returns co-accessed neighbors and their SR distances.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "memory_id": {
                "type": "integer",
                "description": "Starting memory ID for navigation",
            },
            "max_depth": {
                "type": "integer",
                "description": "BFS depth (default 2, max 4)",
            },
            "include_2d_map": {
                "type": "boolean",
                "description": "Include 2D coordinates for visualization (default false)",
            },
            "window_hours": {
                "type": "number",
                "description": "Co-access time window in hours (default 2.0)",
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


# ── Helpers ───────────────────────────────────────────────────────────────


def _enrich_neighbors(
    navigation: dict,
    store: MemoryStore,
) -> list[dict]:
    """Attach memory content and metadata to SR navigation results."""
    neighbors = []
    for mid, nav_info in sorted(navigation.items(), key=lambda x: x[1]["distance"]):
        mem = store.get_memory(mid)
        if not mem:
            continue
        neighbors.append(
            {
                "memory_id": mid,
                "sr_distance": nav_info["distance"],
                "hops": nav_info["hops"],
                "path": nav_info["path"],
                "content": mem["content"][:200],
                "heat": round(mem.get("heat", 0), 4),
                "domain": mem.get("domain", ""),
                "tags": mem.get("tags", []),
            }
        )
    return neighbors


def _build_sr_graph(
    start_id: int,
    start_mem: dict,
    store: MemoryStore,
    window_hours: float,
) -> dict:
    """Build temporal co-access graph ensuring start memory is included."""
    all_mems = store.get_recently_accessed_memories(limit=200, min_access_count=1)
    if not any(m["id"] == start_id for m in all_mems):
        all_mems = [start_mem] + all_mems
    return build_temporal_co_access(all_mems, window_hours=window_hours)


# ── Handler ───────────────────────────────────────────────────────────────


def _build_empty_navigation(start_id: int, sr_graph_size: int) -> dict[str, Any]:
    """Build the empty result when no co-access neighbors are found."""
    return {
        "start_memory_id": start_id,
        "neighbors": [],
        "total": 0,
        "sr_graph_size": sr_graph_size,
        "reason": "no_co_access_neighbors_found",
    }


def _attach_2d_coordinates(
    result: dict[str, Any],
    sr_graph: dict,
    start_id: int,
    neighbors: list[dict],
) -> None:
    """Add optional 2D projection coordinates to result."""
    all_ids = [start_id] + [n["memory_id"] for n in neighbors]
    coords = project_to_2d(sr_graph, all_ids)
    result["coordinates_2d"] = {str(mid): list(xy) for mid, xy in coords.items()}


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Navigate memory space from a starting memory using SR co-access."""
    if not args or args.get("memory_id") is None:
        return {"neighbors": [], "total": 0}

    start_id = int(args["memory_id"])
    max_depth = min(int(args.get("max_depth", 2)), 4)
    include_2d = args.get("include_2d_map", False)
    window_hours = float(args.get("window_hours", 2.0))

    store = _get_store()
    start_mem = store.get_memory(start_id)
    if not start_mem:
        return {"neighbors": [], "total": 0, "reason": "memory_not_found"}

    sr_graph = _build_sr_graph(start_id, start_mem, store, window_hours)
    navigation = navigate_from(start_id, sr_graph, max_depth=max_depth)

    if not navigation:
        return _build_empty_navigation(start_id, len(sr_graph))

    neighbors = _enrich_neighbors(navigation, store)

    # Track replay for start memory and traversed neighbors
    for mem_id in [start_id] + [n.get("memory_id") for n in navigation if n.get("memory_id")]:
        try:
            store.update_memory_access(mem_id)
            store.increment_replay_count(mem_id)
        except Exception:
            pass

    result: dict[str, Any] = {
        "start_memory_id": start_id,
        "start_content": start_mem["content"],
        "neighbors": neighbors,
        "total": len(neighbors),
        "max_depth": max_depth,
        "sr_graph_size": len(sr_graph),
    }

    if include_2d and neighbors:
        _attach_2d_coordinates(result, sr_graph, start_id, neighbors)

    return result
