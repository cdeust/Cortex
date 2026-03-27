"""Memory and entity node construction for the unified graph builder.

Handles memory nodes (with emotional tagging) and entity nodes.
Pure business logic -- no I/O.

Domain resolution strategy:
  1. Entity/memory domain matches a profile hub exactly → use it
  2. Entity/memory domain fuzzy-matches a hub (substring) → use it
  3. Memory mentions an entity that is already linked to a hub → follow that edge
  4. No match → node is left unlinked (no forced fallback)
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
from mcp_server.core.knowledge_graph import extract_entities


# ── Domain resolution ──────────────────────────────────────────────────


def _resolve_hub(
    domain: str,
    domain_hub_ids: dict[str, str],
) -> str | None:
    """Resolve a domain string to a hub key. Exact match, then substring."""
    if not domain:
        return None
    if domain in domain_hub_ids:
        return domain
    low = domain.lower()
    for key in domain_hub_ids:
        if low in key.lower() or key.lower() in low:
            return key
    return None


def _build_entity_hub_map(
    sorted_entities: list[dict],
    domain_hub_ids: dict[str, str],
) -> dict[int, str]:
    """Pre-compute entity DB id → resolved hub key for all entities."""
    mapping: dict[int, str] = {}
    for ent in sorted_entities:
        db_id = ent.get("id")
        if db_id is None:
            continue
        hub = _resolve_hub(ent.get("domain", ""), domain_hub_ids)
        if hub is not None:
            mapping[db_id] = hub
    return mapping


# ── Entity nodes ────────────────────────────────────────────────────────


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
    """Add entity nodes with domain-entity edges via resolved hub mapping."""
    entity_hub_map = _build_entity_hub_map(sorted_entities, domain_hub_ids)

    for ent in sorted_entities:
        nid = next_id("ent")
        db_id = ent.get("id")
        if db_id is not None:
            entity_id_map[db_id] = nid
        nodes.append(_build_entity_node(ent, nid))

        heat = ent.get("heat", 0)
        hub_key = entity_hub_map.get(db_id) if db_id is not None else None
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


# ── Memory nodes ────────────────────────────────────────────────────────


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
    """Find the best matching entity node for a memory via text overlap."""
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


def _find_hub_via_entity(
    entity_nid: str,
    edges: list[Edge],
    domain_hub_ids: dict[str, str],
) -> str | None:
    """Given an entity node id, find which hub it's connected to."""
    hub_id_to_key = {hid: key for key, hid in domain_hub_ids.items()}
    for e in edges:
        if e.get("type") != "domain-entity":
            continue
        if e["target"] == entity_nid and e["source"] in hub_id_to_key:
            return hub_id_to_key[e["source"]]
        if e["source"] == entity_nid and e["target"] in hub_id_to_key:
            return hub_id_to_key[e["target"]]
    return None


def _get_or_create_entity_node(
    name: str,
    ent_type: str,
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
    domain_hub_ids: dict[str, str],
    inline_entities: dict[str, str],
) -> str:
    """Return node id for an inline entity, creating if needed.

    Inline entities are extracted at graph build time from memory content.
    They act as bridge nodes between memories and domain hubs.
    """
    key = name.lower()
    if key in inline_entities:
        return inline_entities[key]

    nid = next_id("ient")
    nodes.append(
        {
            "id": nid,
            "type": "entity",
            "label": name,
            "domain": "",
            "color": ENTITY_COLORS.get(ent_type, "#00d2ff"),
            "size": 2,
            "group": "_entities",
            "entityType": ent_type,
            "heat": 0,
            "content": name,
        }
    )
    inline_entities[key] = nid

    # Link to the first domain hub — entities are global connectors
    if domain_hub_ids:
        hub_key = next(iter(domain_hub_ids))
        edges.append(
            {
                "source": domain_hub_ids[hub_key],
                "target": nid,
                "type": "domain-entity",
                "weight": 0.15,
                "color": EDGE_COLORS["domain-entity"],
            }
        )
    return nid


def _link_memory(
    nid: str,
    mem: dict,
    mem_domain: str,
    entity_names: dict[str, str],
    nodes: list[Node],
    edges: list[Edge],
    domain_hub_ids: dict[str, str],
    next_id: IdAllocator,
    inline_entities: dict[str, str],
) -> None:
    """Link a memory node via the best available strategy.

    Resolution chain:
      1. Existing DB entity match (text overlap) → memory-entity edge
      2. Memory domain matches a hub → domain-entity edge
      3. Extract entities from content → create inline entity nodes as bridges
      4. No entities found → unlinked (accurate representation)
    """
    # Strategy 1: match against existing entity nodes
    best_match, best_score = _find_best_entity_match(
        mem, mem_domain, entity_names, nodes
    )
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

    # Strategy 2: resolve domain directly
    hub_key = _resolve_hub(mem_domain, domain_hub_ids)
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
        return

    # Strategy 3: extract entities from content and create bridge nodes
    content = mem.get("content", "")
    extracted = extract_entities(content)
    if extracted:
        for ent in extracted[:3]:  # Cap at 3 entities per memory
            ent_nid = _get_or_create_entity_node(
                ent["name"],
                ent["type"],
                next_id,
                nodes,
                edges,
                domain_hub_ids,
                inline_entities,
            )
            edges.append(
                {
                    "source": nid,
                    "target": ent_nid,
                    "type": "memory-entity",
                    "weight": 0.5,
                    "color": EDGE_COLORS["memory-entity"],
                }
            )
        return

    # Strategy 4: no entities found — memory stays unlinked


def add_memory_nodes(
    sorted_memories: list[dict],
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
    domain_hub_ids: dict[str, str],
    entity_names: dict[str, str],
) -> None:
    """Add memory nodes with emotional tagging and entity/domain edges."""
    inline_entities: dict[str, str] = {}

    for mem in sorted_memories:
        nid = next_id("mem")
        content = mem.get("content", "")
        mem_domain = mem.get("domain", "")
        emo = tag_memory_emotions(content)
        color = _resolve_memory_color(emo, mem.get("store_type", "episodic"))
        nodes.append(_build_memory_node(mem, nid, emo, color))

        _link_memory(
            nid,
            mem,
            mem_domain,
            entity_names,
            nodes,
            edges,
            domain_hub_ids,
            next_id,
            inline_entities,
        )
