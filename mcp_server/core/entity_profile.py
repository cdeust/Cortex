"""Entity profile builder — compute navigable entity profiles from memory data.

Pure business logic: no I/O. Takes entity, memories, and relationships
as dicts and returns a structured entity profile suitable for the
entity detail view in the unified visualization.
"""

from __future__ import annotations

from typing import Any


def build_entity_profile(
    entity: dict[str, Any],
    memories: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a full entity profile from raw data.

    Args:
        entity: Entity dict with id, name, type, domain, heat.
        memories: Memories mentioning this entity, each with id, content,
            heat, created_at, store_type, domain.
        relationships: Relationships involving this entity, each with
            source_entity_id, target_entity_id, relationship_type, weight.

    Returns:
        Profile dict with stats, top memories, related entities, temporal span.
    """
    stats = compute_entity_stats(memories)
    top_memories = _select_top_memories(memories, limit=10)
    related = _extract_related_entities(entity["id"], relationships)
    temporal = _compute_temporal_span(memories)

    return {
        "entity_id": entity["id"],
        "name": entity.get("name", ""),
        "type": entity.get("type", ""),
        "domain": entity.get("domain", ""),
        "heat": entity.get("heat", 0.0),
        "mention_count": stats["total_mentions"],
        "domains": stats["domains"],
        "temporal_span": temporal,
        "top_memories": top_memories,
        "related_entities": related,
        "stats": stats,
    }


def compute_entity_stats(memories: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate statistics from memories mentioning an entity.

    Returns:
        Dict with total_mentions, domains, episodic_count, semantic_count, avg_heat.
    """
    if not memories:
        return {
            "total_mentions": 0,
            "domains": [],
            "episodic_count": 0,
            "semantic_count": 0,
            "avg_heat": 0.0,
        }

    domains: set[str] = set()
    episodic = 0
    semantic = 0
    heat_sum = 0.0

    for m in memories:
        d = m.get("domain", "")
        if d:
            domains.add(d)
        st = m.get("store_type", "episodic")
        if st == "semantic":
            semantic += 1
        else:
            episodic += 1
        heat_sum += m.get("heat", 0.0)

    return {
        "total_mentions": len(memories),
        "domains": sorted(domains),
        "episodic_count": episodic,
        "semantic_count": semantic,
        "avg_heat": round(heat_sum / len(memories), 4),
    }


def _select_top_memories(
    memories: list[dict[str, Any]], limit: int = 10
) -> list[dict[str, Any]]:
    """Select the top memories by heat, returning lightweight summaries."""
    sorted_mems = sorted(memories, key=lambda m: m.get("heat", 0.0), reverse=True)
    result = []
    for m in sorted_mems[:limit]:
        content = m.get("content", "")
        result.append({
            "id": m.get("id"),
            "content_preview": content[:120] if content else "",
            "heat": m.get("heat", 0.0),
            "domain": m.get("domain", ""),
            "store_type": m.get("store_type", "episodic"),
            "created_at": str(m.get("created_at", "")),
        })
    return result


def _extract_related_entities(
    entity_id: int, relationships: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Extract related entity references from relationships."""
    related: list[dict[str, Any]] = []
    seen: set[int] = set()

    for rel in relationships:
        src = rel.get("source_entity_id")
        tgt = rel.get("target_entity_id")
        other_id = tgt if src == entity_id else src
        if other_id is None or other_id in seen:
            continue
        seen.add(other_id)
        related.append({
            "entity_id": other_id,
            "relationship_type": rel.get("relationship_type", "related"),
            "weight": rel.get("weight", 1.0),
            "name": rel.get("target_name", rel.get("source_name", "")),
            "type": rel.get("target_type", rel.get("source_type", "")),
        })

    return sorted(related, key=lambda r: r["weight"], reverse=True)


def _compute_temporal_span(
    memories: list[dict[str, Any]],
) -> dict[str, str | None]:
    """Compute first_seen and last_seen from memory timestamps."""
    if not memories:
        return {"first_seen": None, "last_seen": None}

    dates = []
    for m in memories:
        created = m.get("created_at")
        if created:
            dates.append(str(created))

    if not dates:
        return {"first_seen": None, "last_seen": None}

    dates.sort()
    return {"first_seen": dates[0], "last_seen": dates[-1]}
