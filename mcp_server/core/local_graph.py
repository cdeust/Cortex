"""Local graph construction for Obsidian-like memory navigation.

Takes pre-fetched data from infrastructure layer and builds a typed
graph structure for frontend rendering. The center memory is highlighted,
with entity nodes and neighbor memories arranged around it.

Node types:
  center_memory  — the selected memory (gold)
  neighbor_memory — memories sharing entities with center (blue)
  entity         — entities linked to center (teal)

Edge types:
  mention    — memory → entity (this memory mentions this entity)
  backlink   — entity → memory (this entity appears in this memory)
  co_entity  — memory → memory (share one or more entities)
  relationship — entity → entity (knowledge graph edge)

Pure business logic — no I/O.
"""

from __future__ import annotations

from typing import Any


def build_local_graph(
    center: dict[str, Any],
    entities: list[dict[str, Any]],
    neighbors: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a typed graph from pre-fetched neighborhood data.

    Args:
        center: The center memory dict (id, content, heat, ...).
        entities: Entities linked to the center memory.
        neighbors: Memories sharing entities with center.
        relationships: Entity-entity edges.

    Returns:
        {nodes: [...], edges: [...], center_id: int, stats: {...}}
    """
    if not center:
        return {"nodes": [], "edges": [], "center_id": None, "stats": {}}

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    node_ids: set[str] = set()

    center_id = f"m:{center['id']}"

    # Center memory node
    nodes.append(_memory_node(center, "center_memory"))
    node_ids.add(center_id)

    # Entity nodes + mention edges from center
    entity_id_set: set[int] = set()
    for entity in entities:
        eid = f"e:{entity['id']}"
        if eid not in node_ids:
            nodes.append(_entity_node(entity))
            node_ids.add(eid)
            entity_id_set.add(entity["id"])
        edges.append({
            "source": center_id,
            "target": eid,
            "type": "mention",
            "weight": entity.get("confidence", 1.0),
        })

    # Neighbor memory nodes + co_entity edges
    for neighbor in neighbors:
        nid = f"m:{neighbor['id']}"
        if nid not in node_ids:
            nodes.append(_memory_node(neighbor, "neighbor_memory"))
            node_ids.add(nid)
        shared = neighbor.get("shared_entity_count", 1)
        edges.append({
            "source": center_id,
            "target": nid,
            "type": "co_entity",
            "weight": min(shared / max(len(entities), 1), 1.0),
            "shared_entities": shared,
        })

    # Entity-entity relationship edges
    for rel in relationships:
        src = f"e:{rel['source_entity_id']}"
        tgt = f"e:{rel['target_entity_id']}"
        if src in node_ids and tgt in node_ids:
            edges.append({
                "source": src,
                "target": tgt,
                "type": "relationship",
                "relationship_type": rel.get("relationship_type", "related"),
                "weight": rel.get("weight", 0.5),
                "is_causal": rel.get("is_causal", False),
            })

    return {
        "nodes": nodes,
        "edges": edges,
        "center_id": center_id,
        "stats": {
            "entity_count": len(entity_id_set),
            "neighbor_count": len(neighbors),
            "edge_count": len(edges),
        },
    }


def _memory_node(memory: dict[str, Any], node_type: str) -> dict[str, Any]:
    """Create a memory node for the local graph."""
    content = memory.get("content", "")
    return {
        "id": f"m:{memory['id']}",
        "memory_id": memory["id"],
        "type": node_type,
        "label": content[:80] + ("..." if len(content) > 80 else ""),
        "content": content[:300],
        "heat": memory.get("heat", 0.5),
        "importance": memory.get("importance", 0.5),
        "domain": memory.get("domain", ""),
        "store_type": memory.get("store_type", "episodic"),
        "tags": memory.get("tags", []),
        "created_at": str(memory.get("created_at", "")),
        "is_protected": memory.get("is_protected", False),
        "is_global": memory.get("is_global", False),
    }


def _entity_node(entity: dict[str, Any]) -> dict[str, Any]:
    """Create an entity node for the local graph."""
    return {
        "id": f"e:{entity['id']}",
        "entity_id": entity["id"],
        "type": "entity",
        "label": entity.get("name", ""),
        "entity_type": entity.get("type", "concept"),
        "domain": entity.get("domain", ""),
        "heat": entity.get("heat", 0.5),
        "confidence": entity.get("confidence", 1.0),
    }
