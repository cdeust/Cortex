"""Memory and entity node construction for the unified graph builder.

Handles memory nodes (with emotional tagging) and entity nodes.
Pure business logic -- no I/O.
"""

from __future__ import annotations


from mcp_server.core.emotional_tagging import tag_memory_emotions
from mcp_server.core.graph_builder_nodes import (
    EDGE_COLORS,
    ENTITY_COLORS,
    MEMORY_COLORS,
    Edge,
    IdAllocator,
    Node,
)


def _build_entity_node(ent: dict, nid: str) -> Node:
    """Construct a single entity node dict."""
    ent_type = ent.get("type", "unknown")
    heat = ent.get("heat", 0)
    return {
        "id": nid,
        "type": "entity",
        "label": ent.get("name", ""),
        "domain": ent.get("domain", ""),
        "color": ENTITY_COLORS.get(ent_type, "#00d2ff"),
        "size": max(2, 2 + heat * 4),
        "group": ent.get("domain", "") or "_entities",
        "entityType": ent_type,
        "heat": round(heat, 4),
        "content": ent.get("name", ""),
    }


def add_entity_nodes(
    sorted_entities: list[dict],
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
    domain_hub_ids: dict[str, str],
    entity_id_map: dict[int, str],
) -> None:
    """Add entity nodes and domain-entity edges."""
    for ent in sorted_entities:
        nid = next_id("ent")
        db_id = ent.get("id")
        if db_id is not None:
            entity_id_map[db_id] = nid
        nodes.append(_build_entity_node(ent, nid))

        ent_domain = ent.get("domain", "")
        heat = ent.get("heat", 0)

        # Resolve hub: exact match, fuzzy match, or first available
        hub_key = None
        if ent_domain and ent_domain in domain_hub_ids:
            hub_key = ent_domain
        elif ent_domain:
            hub_key = _find_closest_domain(ent_domain, domain_hub_ids)
        if hub_key is None and domain_hub_ids:
            hub_key = next(iter(domain_hub_ids))

        if hub_key is not None:
            edges.append(
                {
                    "source": domain_hub_ids[hub_key],
                    "target": nid,
                    "type": "domain-entity",
                    "weight": 0.3 + heat * 0.4,
                    "color": EDGE_COLORS["domain-entity"],
                }
            )


def _resolve_memory_color(emo: dict, store_type: str) -> str:
    """Pick memory node color based on emotional tagging."""
    if not emo["is_emotional"]:
        return MEMORY_COLORS.get(store_type, "#26de81")
    emotion_colors = {
        "urgency": "#ff3366",
        "frustration": "#ef4444",
        "satisfaction": "#22c55e",
        "discovery": "#f59e0b",
        "confusion": "#8b5cf6",
    }
    return emotion_colors.get(
        emo["dominant_emotion"],
        MEMORY_COLORS.get(store_type, "#26de81"),
    )


def _build_memory_node(mem: dict, nid: str, emo: dict, color: str) -> Node:
    """Construct a single memory node dict."""
    heat = mem.get("heat", 0)
    importance = mem.get("importance", 0.5)
    content = mem.get("content", "")
    valence = mem.get("emotional_valence", 0)
    size = max(1.5, 2 + importance * 3 + heat * 2)
    if emo["is_emotional"]:
        size *= min(emo["importance_boost"], 1.5)
    label = content[:40].replace("\n", " ") + ("..." if len(content) > 40 else "")
    return {
        "id": nid,
        "type": "memory",
        "label": label,
        "domain": mem.get("domain", ""),
        "color": color,
        "size": round(size, 2),
        "group": mem.get("domain", "") or "_memories",
        "heat": round(heat, 4),
        "importance": round(importance, 4),
        "storeType": mem.get("store_type", "episodic"),
        "isProtected": bool(mem.get("is_protected", False)),
        "accessCount": mem.get("access_count", 0),
        "tags": mem.get("tags", []),
        "content": content[:500],
        "emotion": emo["dominant_emotion"],
        "arousal": emo["arousal"],
        "valence": round(valence, 4),
        "emotionalBoost": round(emo["importance_boost"], 4),
        "decayResistance": round(emo["decay_resistance"], 4),
    }


def _find_best_entity_match(
    mem: dict,
    mem_domain: str,
    entity_names: dict[str, str],
    nodes: list[Node],
) -> tuple[str | None, float]:
    """Find the best matching entity node for a memory."""
    content = mem.get("content", "")
    mem_text = (content + " " + " ".join(mem.get("tags") or [])).lower()
    best_match: str | None = None
    best_score = 0.0
    for ent_name, ent_nid in entity_names.items():
        score = 0.6 if ent_name in mem_text else 0.0
        ent_node = next((n for n in nodes if n["id"] == ent_nid), None)
        if ent_node and ent_node.get("domain") == mem_domain and mem_domain:
            score += 0.3
        if score > best_score:
            best_score = score
            best_match = ent_nid
    return best_match, best_score


def _find_closest_domain(
    mem_domain: str,
    domain_hub_ids: dict[str, str],
) -> str | None:
    """Fuzzy-match a memory domain to the closest domain hub key."""
    if not mem_domain:
        return None
    low = mem_domain.lower()
    for key in domain_hub_ids:
        if low in key.lower() or key.lower() in low:
            return key
    return None


def _add_memory_edge(
    nid: str,
    best_match: str | None,
    best_score: float,
    mem_domain: str,
    domain_hub_ids: dict[str, str],
    edges: list[Edge],
) -> None:
    """Add memory-entity or domain-entity edge for a memory node."""
    if best_match and best_score > 0.2:
        edges.append(
            {
                "source": nid,
                "target": best_match,
                "type": "memory-entity",
                "weight": min(best_score, 0.7),
                "color": EDGE_COLORS["memory-entity"],
            }
        )
        return

    # Try exact domain match, then fuzzy match, then first available hub
    hub_key = None
    if mem_domain and mem_domain in domain_hub_ids:
        hub_key = mem_domain
    elif mem_domain:
        hub_key = _find_closest_domain(mem_domain, domain_hub_ids)
    if hub_key is None and domain_hub_ids:
        hub_key = next(iter(domain_hub_ids))

    if hub_key is not None:
        edges.append(
            {
                "source": domain_hub_ids[hub_key],
                "target": nid,
                "type": "domain-entity",
                "weight": 0.2,
                "color": EDGE_COLORS["domain-entity"],
            }
        )


def add_memory_nodes(
    sorted_memories: list[dict],
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
    domain_hub_ids: dict[str, str],
    entity_names: dict[str, str],
) -> None:
    """Add memory nodes with emotional tagging and entity/domain edges."""
    for mem in sorted_memories:
        nid = next_id("mem")
        content = mem.get("content", "")
        mem_domain = mem.get("domain", "")
        emo = tag_memory_emotions(content)
        color = _resolve_memory_color(emo, mem.get("store_type", "episodic"))
        nodes.append(_build_memory_node(mem, nid, emo, color))

        best_match, best_score = _find_best_entity_match(
            mem,
            mem_domain,
            entity_names,
            nodes,
        )
        _add_memory_edge(
            nid,
            best_match,
            best_score,
            mem_domain,
            domain_hub_ids,
            edges,
        )
