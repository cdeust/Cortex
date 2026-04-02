"""Handler: get_causal_chain — trace entity relationships through the knowledge graph.

Given an entity name (or memory ID), performs BFS through the relationship
graph to surface chains of causation, dependency, and resolution.

Useful for: understanding why a bug occurred, tracing a decision's origin,
following an import chain across modules.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

# ── Schema ────────────────────────────────────────────────────────────────

schema = {
    "description": "Trace entity relationships through the knowledge graph. Returns causal/dependency chains from a starting entity or memory.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "entity_name": {
                "type": "string",
                "description": "Name of the entity to trace from (e.g. 'DatabaseError')",
            },
            "memory_id": {
                "type": "integer",
                "description": "Memory ID to extract starting entities from",
            },
            "relationship_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Filter to specific relationship types (e.g. ['caused_by', 'resolved_by', 'imports']). Default: all.",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum BFS depth (default 3)",
            },
            "max_edges": {
                "type": "integer",
                "description": "Maximum edges to return (default 200)",
            },
            "direction": {
                "type": "string",
                "enum": ["outgoing", "incoming", "both"],
                "description": "Traversal direction (default 'both')",
            },
        },
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


# ── BFS traversal ─────────────────────────────────────────────────────────


def _build_edge_record(
    rel: dict,
    store: MemoryStore,
    depth: int,
) -> dict[str, Any]:
    """Resolve entity names and build a single edge record."""
    src_id = rel["source_entity_id"]
    tgt_id = rel["target_entity_id"]
    src = store.get_entity_by_id(src_id)
    tgt = store.get_entity_by_id(tgt_id)

    return {
        "source_id": src_id,
        "source_name": src["name"] if src else f"entity:{src_id}",
        "source_type": src["type"] if src else "unknown",
        "target_id": tgt_id,
        "target_name": tgt["name"] if tgt else f"entity:{tgt_id}",
        "target_type": tgt["type"] if tgt else "unknown",
        "relationship_type": rel["relationship_type"],
        "weight": round(rel.get("weight", 1.0), 4),
        "confidence": round(rel.get("confidence", 1.0), 4),
        "depth": depth,
    }


def _bfs_entity_graph(
    start_entity_id: int,
    store: MemoryStore,
    max_depth: int,
    max_edges: int,
    direction: str,
    rel_filter: set[str] | None,
) -> list[dict[str, Any]]:
    """BFS through the entity relationship graph from start_entity_id."""
    visited_entities: set[int] = {start_entity_id}
    queue: deque[tuple[int, int]] = deque([(start_entity_id, 0)])
    edges: list[dict[str, Any]] = []

    while queue:
        if len(edges) >= max_edges:
            break
        entity_id, depth = queue.popleft()
        if depth >= max_depth:
            continue

        rels = store.get_relationships_for_entity(
            entity_id, direction=direction, limit=20
        )
        for rel in rels:
            if len(edges) >= max_edges:
                break
            if rel_filter and rel.get("relationship_type") not in rel_filter:
                continue

            edges.append(_build_edge_record(rel, store, depth + 1))

            for next_id in (rel["source_entity_id"], rel["target_entity_id"]):
                if next_id not in visited_entities:
                    visited_entities.add(next_id)
                    queue.append((next_id, depth + 1))

    return edges


# ── Entity resolution ────────────────────────────────────────────────────


def _resolve_start_entity_by_name(
    entity_name: str,
    store: MemoryStore,
) -> dict | None:
    """Look up a starting entity by name."""
    return store.get_entity_by_name(entity_name)


def _resolve_start_entity_from_memory(
    memory_id: int,
    store: MemoryStore,
) -> dict | None:
    """Extract the first known entity from a memory's content."""
    mem = store.get_memory(memory_id)
    if not mem:
        return None

    from mcp_server.core.knowledge_graph import extract_entities

    extracted = extract_entities(mem.get("content", ""))
    for ent in extracted:
        found = store.get_entity_by_name(ent["name"])
        if found:
            return found
    return None


def _build_empty_result(reason: str) -> dict[str, Any]:
    return {"chain": [], "total_edges": 0, "reason": reason}


def _resolve_start_entity(
    args: dict[str, Any],
    store: MemoryStore,
) -> tuple[dict | None, str | None]:
    """Resolve starting entity from args. Returns (entity, error_reason)."""
    if args.get("entity_name"):
        entity = _resolve_start_entity_by_name(args["entity_name"], store)
        if not entity:
            return None, f"entity not found: {args['entity_name']}"
        return entity, None

    entity = _resolve_start_entity_from_memory(int(args["memory_id"]), store)
    if not entity:
        return None, "no known entities found in memory"
    return entity, None


def _get_related_memory_previews(
    store: MemoryStore,
    entity_name: str,
) -> list[dict]:
    """Fetch and format memory previews mentioning an entity."""
    related = store.get_memories_mentioning_entity(entity_name, limit=5)
    return [
        {
            "memory_id": m["id"],
            "content": m["content"][:150],
            "heat": round(m.get("heat", 0), 4),
        }
        for m in related
    ]


# ── Handler ───────────────────────────────────────────────────────────────


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Trace causal/dependency chain from an entity or memory."""
    args = args or {}

    if not args.get("entity_name") and args.get("memory_id") is None:
        return _build_empty_result("provide entity_name or memory_id")

    max_depth = min(int(args.get("max_depth", 3)), 5)
    max_edges = min(int(args.get("max_edges", 50)), 200)
    direction = args.get("direction", "both")
    rel_types = args.get("relationship_types")
    rel_filter = set(rel_types) if rel_types else None

    store = _get_store()
    start_entity, error = _resolve_start_entity(args, store)
    if not start_entity:
        return _build_empty_result(error)

    edges = _bfs_entity_graph(
        start_entity_id=start_entity["id"],
        store=store,
        max_depth=max_depth,
        max_edges=max_edges,
        direction=direction,
        rel_filter=rel_filter,
    )

    return {
        "start_entity": {
            "id": start_entity["id"],
            "name": start_entity["name"],
            "type": start_entity["type"],
        },
        "chain": edges,
        "total_edges": len(edges),
        "related_memories": _get_related_memory_previews(store, start_entity["name"]),
        "max_depth": max_depth,
        "direction": direction,
    }
