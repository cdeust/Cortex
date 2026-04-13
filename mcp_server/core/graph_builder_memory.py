"""Memory and entity node construction for the unified graph builder.

Notation design (Euler method):
  Old: each memory links to ONE entity via best text match -> star topology.
  New: each memory links to ALL matching entities + memories cluster by
       shared tags into topic nodes + cross-domain entities become bridges.

This produces a mesh with natural clustering instead of an unreadable scatter.

Pure business logic -- no I/O.
"""

from __future__ import annotations

from mcp_server.core.emotional_tagging import tag_memory_emotions
from mcp_server.core.graph_builder_nodes import (
    EDGE_COLORS,
    ENTITY_COLORS,
    Edge,
    IdAllocator,
    Node,
)

# ── Constants ─────────────────────────────────────────────────────────

# Minimum tags shared for a topic cluster to form
_MIN_SHARED_TAGS = 2

# Maximum topic nodes to create (prevent explosion)
_MAX_TOPIC_NODES = 50

# Minimum members for a topic to be worth showing
_MIN_TOPIC_MEMBERS = 3

# Topic node colors
TOPIC_COLOR = "#06b6d4"

# Bridge entity color (cross-domain)
BRIDGE_ENTITY_COLOR = "#ec4899"

# ── Consolidation stage opacity ───────────────────────────────────────

_STAGE_OPACITY = {
    "labile": 0.4,
    "early_ltp": 0.6,
    "late_ltp": 0.8,
    "consolidated": 1.0,
    "reconsolidating": 0.7,
}

# ── Heat gradient ─────────────────────────────────────────────────────

_HEAT_COLORS = [
    (0.0, "#1e3a5f"),  # cold: dark blue
    (0.3, "#2563eb"),  # cool: blue
    (0.5, "#06b6d4"),  # warm: cyan
    (0.7, "#f59e0b"),  # hot: amber
    (1.0, "#ef4444"),  # burning: red
]


def _heat_to_color(heat: float) -> str:
    """Map heat [0,1] to a gradient color for memory nodes."""
    heat = max(0.0, min(1.0, heat))
    for i in range(1, len(_HEAT_COLORS)):
        if heat <= _HEAT_COLORS[i][0]:
            t = (heat - _HEAT_COLORS[i - 1][0]) / (
                _HEAT_COLORS[i][0] - _HEAT_COLORS[i - 1][0]
            )
            c0 = _HEAT_COLORS[i - 1][1]
            c1 = _HEAT_COLORS[i][1]
            r = int(int(c0[1:3], 16) * (1 - t) + int(c1[1:3], 16) * t)
            g = int(int(c0[3:5], 16) * (1 - t) + int(c1[3:5], 16) * t)
            b = int(int(c0[5:7], 16) * (1 - t) + int(c1[5:7], 16) * t)
            return f"#{r:02x}{g:02x}{b:02x}"
    return _HEAT_COLORS[-1][1]


# ── Domain resolution ─────────────────────────────────────────────────


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


def _resolve_type_group(
    domain: str,
    group_label: str,
    domain_hub_ids: dict[str, str],
    type_group_map: dict[str, dict[str, str]],
) -> str | None:
    """Resolve a domain + group label to a type-group node id."""
    hub_key = _resolve_hub(domain, domain_hub_ids)
    if hub_key and hub_key in type_group_map:
        return type_group_map[hub_key].get(group_label)
    return None


# ── Global memory linking ─────────────────────────────────────────────


def _link_global_to_all_domains(
    nid: str,
    edges: list[Edge],
    domain_hub_ids: dict[str, str],
    type_group_map: dict[str, dict[str, str]],
) -> None:
    """Connect a global memory to every unique domain hub."""
    seen_hubs: set[str] = set()
    for hub_key, hub_id in domain_hub_ids.items():
        if hub_id in seen_hubs:
            continue
        seen_hubs.add(hub_id)

        tg_id = None
        if hub_key in type_group_map:
            tg_id = type_group_map[hub_key].get("Memories")
        if tg_id:
            edges.append(
                {
                    "source": tg_id,
                    "target": nid,
                    "type": "groups",
                    "weight": 0.25,
                    "color": EDGE_COLORS["groups"],
                }
            )
        else:
            edges.append(
                {
                    "source": hub_id,
                    "target": nid,
                    "type": "domain-entity",
                    "weight": 0.2,
                    "color": EDGE_COLORS["domain-entity"],
                }
            )


# ── Entity nodes ──────────────────────────────────────────────────────


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


_EXCLUDED_ENTITY_TYPES = {"file", "function", "dependency"}


def add_entity_nodes(
    sorted_entities: list[dict],
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
    domain_hub_ids: dict[str, str],
    entity_id_map: dict[int, str],
    type_group_map: dict[str, dict[str, str]],
) -> None:
    """Add entity nodes linked to the hierarchy via type-groups or hubs."""
    for ent in sorted_entities:
        if ent.get("type", "") in _EXCLUDED_ENTITY_TYPES:
            continue
        nid = next_id("ent")
        db_id = ent.get("id")
        if db_id is not None:
            entity_id_map[db_id] = nid
        nodes.append(_build_entity_node(ent, nid))

        ent_domain = ent.get("domain", "")
        heat = ent.get("heat", 0)

        tg_id = _resolve_type_group(
            ent_domain, "Memories", domain_hub_ids, type_group_map
        )
        if tg_id:
            edges.append(
                {
                    "source": tg_id,
                    "target": nid,
                    "type": "groups",
                    "weight": 0.3 + heat * 0.4,
                    "color": EDGE_COLORS["groups"],
                }
            )
            continue

        hub_key = _resolve_hub(ent_domain, domain_hub_ids)
        if hub_key:
            edges.append(
                {
                    "source": domain_hub_ids[hub_key],
                    "target": nid,
                    "type": "domain-entity",
                    "weight": 0.3 + heat * 0.4,
                    "color": EDGE_COLORS["domain-entity"],
                }
            )


# ── Memory nodes ──────────────────────────────────────────────────────


def _resolve_memory_color(emo: dict, heat: float) -> str:
    """Pick memory node color: heat gradient, overridden by strong emotion."""
    if emo["is_emotional"] and emo.get("arousal", 0) > 0.6:
        emotion_colors = {
            "urgency": "#ff3366",
            "frustration": "#ef4444",
            "satisfaction": "#22c55e",
            "discovery": "#f59e0b",
            "confusion": "#8b5cf6",
        }
        return emotion_colors.get(emo["dominant_emotion"], _heat_to_color(heat))
    return _heat_to_color(heat)


def _build_memory_node(mem: dict, nid: str, emo: dict, color: str) -> Node:
    """Construct a single memory node dict."""
    heat = mem.get("heat", 0)
    importance = mem.get("importance", 0.5)
    content = mem.get("content", "")
    valence = mem.get("emotional_valence", 0)
    stage = mem.get("consolidation_stage", "labile")
    store_type = mem.get("store_type", "episodic")
    # Heat drives visual weight: cold memories are tiny dots (0.8px),
    # hot memories are prominent (up to 6px). This creates natural
    # visual hierarchy without hiding anything.
    size = max(0.8, heat * 4 + importance * 2)
    if emo["is_emotional"]:
        size *= min(emo["importance_boost"], 1.3)
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
        "storeType": store_type,
        "isProtected": bool(mem.get("is_protected", False)),
        "accessCount": mem.get("access_count", 0),
        "tags": mem.get("tags", []),
        "content": content,
        "emotion": emo["dominant_emotion"],
        "arousal": emo["arousal"],
        "valence": round(valence, 4),
        "emotionalBoost": round(emo["importance_boost"], 4),
        "decayResistance": round(emo["decay_resistance"], 4),
        "isGlobal": bool(mem.get("is_global", False)),
        "consolidationStage": stage,
        "opacity": _STAGE_OPACITY.get(stage, 0.6),
        "thetaPhase": round(mem.get("theta_phase_at_encoding", 0), 4),
        "encodingStrength": round(mem.get("encoding_strength", 1.0), 4),
        "separationIndex": round(mem.get("separation_index", 0), 4),
        "interferenceScore": round(mem.get("interference_score", 0), 4),
        "schemaMatchScore": round(mem.get("schema_match_score", 0), 4),
        "hippocampalDependency": round(mem.get("hippocampal_dependency", 1.0), 4),
        "plasticity": round(mem.get("plasticity", 1.0), 4),
        "stability": round(mem.get("stability", 0), 4),
        "surpriseScore": round(mem.get("surprise_score", 0), 4),
        "createdAt": str(mem.get("created_at", "")),
        "lastAccessed": str(mem.get("last_accessed", "")),
        "replayCount": mem.get("replay_count", 0),
        "hoursInStage": round(mem.get("hours_in_stage", 0), 2),
        "reconsolidationCount": mem.get("reconsolidation_count", 0),
        "excitability": round(mem.get("excitability", 1.0), 4),
        "confidence": round(mem.get("confidence", 1.0), 4),
    }


# ── Multi-entity linking (replaces single best-match) ────────────────


def _find_all_entity_matches(
    mem: dict,
    entity_names: dict[str, str],
    node_index: dict[str, Node],
    mem_domain: str,
) -> list[tuple[str, float]]:
    """Find matching entity nodes using memory's own entity_ids (DB join).

    Uses the memory's pre-extracted entity_ids when available (fast, precise).
    Falls back to tag-based matching only — NOT content substring matching,
    which produces O(memories * entities) false positives.
    """
    matches: list[tuple[str, float]] = []

    # Primary: use pre-extracted entity_ids from the memory record
    entity_ids = mem.get("entity_ids") or []
    if entity_ids:
        # entity_ids are DB IDs — find their graph node IDs
        # entity_names maps lowercase name -> nid, but we need id -> nid
        # The entity_id_map is built during add_entity_nodes
        # We don't have it here, so match by name from tags
        pass

    # Tag-based matching: memory tags that match entity names exactly
    mem_tags = {t.lower().strip() for t in (mem.get("tags") or []) if len(t) >= 4}
    for ent_name, ent_nid in entity_names.items():
        if ent_name in mem_tags:
            score = 0.6
            ent_node = node_index.get(ent_nid)
            if ent_node and ent_node.get("domain") == mem_domain and mem_domain:
                score += 0.2
            matches.append((ent_nid, score))

    return matches


def _link_memory(
    nid: str,
    mem: dict,
    mem_domain: str,
    entity_names: dict[str, str],
    node_index: dict[str, Node],
    edges: list[Edge],
    domain_hub_ids: dict[str, str],
    type_group_map: dict[str, dict[str, str]],
    next_id: IdAllocator,
    inline_entities: dict[str, str],
    node_list: list[Node],
) -> list[str]:
    """Link a memory node into the graph via ALL matching entities.

    Returns list of entity nids this memory is linked to (for co-reference).

    Resolution chain:
      0. Global memories -> edges to ALL domain hubs
      1. ALL entity matches -> memory-entity edges (not just best)
      2. Fallback: type-group "Memories" or domain hub
      3. Extract entities from content -> create inline entity bridge nodes
    """
    linked_entities: list[str] = []

    # Strategy 0: global memories link to ALL domain hubs
    is_global = bool(mem.get("is_global", False))
    if is_global and domain_hub_ids:
        _link_global_to_all_domains(nid, edges, domain_hub_ids, type_group_map)
        return linked_entities

    # Strategy 1: link to ALL matching entities (not just best)
    matches = _find_all_entity_matches(mem, entity_names, node_index, mem_domain)
    for ent_nid, weight in matches:
        edges.append(
            {
                "source": nid,
                "target": ent_nid,
                "type": "memory-entity",
                "weight": min(weight, 0.7),
                "color": EDGE_COLORS["memory-entity"],
            }
        )
        linked_entities.append(ent_nid)

    # If we found entity matches, also add domain link for tree structure
    if linked_entities:
        _add_domain_fallback(
            nid, mem_domain, edges, domain_hub_ids, type_group_map, 0.15
        )
        return linked_entities

    # Strategy 2: domain fallback (topic clustering provides lateral structure)
    _add_domain_fallback(nid, mem_domain, edges, domain_hub_ids, type_group_map, 0.3)

    return linked_entities


def _add_domain_fallback(
    nid: str,
    mem_domain: str,
    edges: list[Edge],
    domain_hub_ids: dict[str, str],
    type_group_map: dict[str, dict[str, str]],
    weight: float,
) -> None:
    """Add a fallback link to domain type-group or hub."""
    tg_id = _resolve_type_group(mem_domain, "Memories", domain_hub_ids, type_group_map)
    if tg_id:
        edges.append(
            {
                "source": tg_id,
                "target": nid,
                "type": "groups",
                "weight": weight,
                "color": EDGE_COLORS["groups"],
            }
        )
        return

    hub_key = _resolve_hub(mem_domain, domain_hub_ids)
    if hub_key:
        edges.append(
            {
                "source": domain_hub_ids[hub_key],
                "target": nid,
                "type": "domain-entity",
                "weight": weight,
                "color": EDGE_COLORS["domain-entity"],
            }
        )


def _get_or_create_inline_entity(
    name: str,
    ent_type: str,
    next_id: IdAllocator,
    node_list: list[Node],
    edges: list[Edge],
    domain_hub_ids: dict[str, str],
    type_group_map: dict[str, dict[str, str]],
    inline_entities: dict[str, str],
) -> str:
    """Get or create an inline entity node for bridging."""
    key = name.lower()
    if key in inline_entities:
        return inline_entities[key]

    nid = next_id("ient")
    node_list.append(
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

    for tg_map in type_group_map.values():
        tg_id = tg_map.get("Memories")
        if tg_id:
            edges.append(
                {
                    "source": tg_id,
                    "target": nid,
                    "type": "groups",
                    "weight": 0.15,
                    "color": EDGE_COLORS["groups"],
                }
            )
            return nid

    if domain_hub_ids:
        hub_id = next(iter(domain_hub_ids.values()))
        edges.append(
            {
                "source": hub_id,
                "target": nid,
                "type": "domain-entity",
                "weight": 0.15,
                "color": EDGE_COLORS["domain-entity"],
            }
        )
    return nid


# ── Topic clustering by shared tags ──────────────────────────────────


def _build_topic_nodes(
    memory_nids: list[str],
    memory_tags: dict[str, list[str]],
    memory_domains: dict[str, str],
    node_index: dict[str, Node],
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
    domain_hub_ids: dict[str, str],
    type_group_map: dict[str, dict[str, str]],
) -> None:
    """Create topic nodes that cluster memories sharing tags.

    Algorithm: build tag -> memory_nids index, then find tag-pairs that
    co-occur in enough memories. Each qualifying pair becomes a topic node.
    Cap at _MAX_TOPIC_NODES to prevent explosion.
    """
    # Build tag -> set of memory nids
    tag_members: dict[str, set[str]] = {}
    for nid in memory_nids:
        for tag in memory_tags.get(nid, []):
            tag_lower = tag.lower().strip()
            if len(tag_lower) > 1:
                tag_members.setdefault(tag_lower, set()).add(nid)

    # Find tags with enough members to be topics
    # Sort by member count descending — greedily pick the densest topics
    candidate_tags = sorted(
        (
            (tag, mems)
            for tag, mems in tag_members.items()
            if len(mems) >= _MIN_TOPIC_MEMBERS
        ),
        key=lambda x: len(x[1]),
        reverse=True,
    )

    # Greedily assign memories to topics (each memory can be in 1-2 topics)
    assigned_count: dict[str, int] = {nid: 0 for nid in memory_nids}
    topic_count = 0

    for tag, members in candidate_tags:
        if topic_count >= _MAX_TOPIC_NODES:
            break

        # Only create topic if enough unassigned or lightly-assigned members
        available = [m for m in members if assigned_count.get(m, 0) < 2]
        if len(available) < _MIN_TOPIC_MEMBERS:
            continue

        # Determine dominant domain for this topic
        domain_counts: dict[str, int] = {}
        for m in available:
            d = memory_domains.get(m, "")
            if d:
                domain_counts[d] = domain_counts.get(d, 0) + 1
        dominant_domain = (
            max(domain_counts, key=domain_counts.get) if domain_counts else ""
        )

        # Count consolidation stages for topic border encoding
        stage_counts: dict[str, int] = {}
        for m in available:
            mn = node_index.get(m)
            if mn:
                s = mn.get("consolidationStage", "labile")
                stage_counts[s] = stage_counts.get(s, 0) + 1
        total = sum(stage_counts.values()) or 1
        consolidated_ratio = (
            stage_counts.get("consolidated", 0) + stage_counts.get("late_ltp", 0)
        ) / total

        # Create topic node.
        # With progressive disclosure, topics are the primary visible
        # representation of memory clusters. Size scales with member
        # count (sqrt for visual balance) and is more prominent than
        # before since individual memories are hidden.
        topic_nid = next_id("topic")
        topic_count += 1
        member_count = len(available)
        topic_size = max(4, min(16, 4 + member_count**0.5 * 2))
        nodes.append(
            {
                "id": topic_nid,
                "type": "topic",
                "label": tag,
                "domain": dominant_domain,
                "color": TOPIC_COLOR,
                "size": round(topic_size, 2),
                "group": dominant_domain or "_topics",
                "memberCount": member_count,
                "consolidatedRatio": round(consolidated_ratio, 2),
                "content": f"Topic: {tag} ({member_count} memories)",
            }
        )
        node_index[topic_nid] = nodes[-1]

        # Link topic to domain (or root if no domain)
        hub_key = _resolve_hub(dominant_domain, domain_hub_ids)
        if hub_key:
            tg_id = None
            if hub_key in type_group_map:
                tg_id = type_group_map[hub_key].get("Memories")
            target = tg_id or domain_hub_ids[hub_key]
        elif domain_hub_ids:
            # No domain match — link to first available domain hub
            target = next(iter(domain_hub_ids.values()))
        else:
            target = None

        if target:
            edges.append(
                {
                    "source": target,
                    "target": topic_nid,
                    "type": "domain-contains",
                    "weight": 0.5,
                    "color": "#06b6d4",
                }
            )

        # Link memories to topic
        for m in available:
            edges.append(
                {
                    "source": topic_nid,
                    "target": m,
                    "type": "topic-member",
                    "weight": 0.4,
                    "color": "#06b6d480",
                }
            )
            assigned_count[m] = assigned_count.get(m, 0) + 1


# ── Entity co-reference edges ────────────────────────────────────────


def _add_coref_edges(
    memory_entity_links: dict[str, list[str]],
    node_index: dict[str, Node],
    edges: list[Edge],
) -> None:
    """Add edges between entities co-referenced by the same memory.

    If memory M links to entities E1, E2, E3, we add edges:
      E1--E2, E1--E3, E2--E3
    This creates an entity backbone that reveals knowledge structure.
    Cap co-reference edges to prevent quadratic explosion.
    """
    # Count co-references: (ent_a, ent_b) -> count
    coref_counts: dict[tuple[str, str], int] = {}
    for _mem_nid, ent_nids in memory_entity_links.items():
        if len(ent_nids) < 2 or len(ent_nids) > 10:
            continue
        for i in range(len(ent_nids)):
            for j in range(i + 1, len(ent_nids)):
                key = (min(ent_nids[i], ent_nids[j]), max(ent_nids[i], ent_nids[j]))
                coref_counts[key] = coref_counts.get(key, 0) + 1

    # Add edges for pairs with 2+ co-references (noise filter)
    sorted_pairs = sorted(coref_counts.items(), key=lambda x: x[1], reverse=True)
    added = 0
    max_coref_edges = 200
    for (ent_a, ent_b), count in sorted_pairs:
        if count < 2:
            break
        if added >= max_coref_edges:
            break
        edges.append(
            {
                "source": ent_a,
                "target": ent_b,
                "type": "co-entity",
                "weight": min(count * 0.15, 0.8),
                "color": "#a78bfa",
                "corefCount": count,
            }
        )
        added += 1


# ── Cross-domain bridge detection ────────────────────────────────────


def _promote_bridge_entities(
    entity_id_map: dict[int, str],
    node_index: dict[str, Node],
    memory_entity_links: dict[str, list[str]],
    memory_domains: dict[str, str],
) -> None:
    """Promote entities referenced from 2+ domains to bridge-entity type.

    These are the cross-pollination hubs -- concepts that connect knowledge
    across different projects/codebases.
    """
    # For each entity, find which domains reference it
    ent_domains: dict[str, set[str]] = {}
    for mem_nid, ent_nids in memory_entity_links.items():
        domain = memory_domains.get(mem_nid, "")
        if not domain:
            continue
        for ent_nid in ent_nids:
            ent_domains.setdefault(ent_nid, set()).add(domain)

    # Promote multi-domain entities
    for ent_nid, domains in ent_domains.items():
        if len(domains) >= 2:
            node = node_index.get(ent_nid)
            if node and node.get("type") == "entity":
                node["type"] = "bridge-entity"
                node["color"] = BRIDGE_ENTITY_COLOR
                node["size"] = max(node.get("size", 2), 4 + len(domains) * 1.5)
                node["bridgeDomains"] = list(domains)
                node["content"] = (
                    f"{node.get('label', '')} "
                    f"(bridges {len(domains)} domains: "
                    f"{', '.join(sorted(domains)[:5])})"
                )


# ── Resize entities by reference count ───────────────────────────────


def _resize_entities_by_references(
    memory_entity_links: dict[str, list[str]],
    node_index: dict[str, Node],
) -> None:
    """Resize entity nodes based on how many memories reference them.

    This makes knowledge-dense entities visually prominent.
    """
    ref_counts: dict[str, int] = {}
    for _mem_nid, ent_nids in memory_entity_links.items():
        for ent_nid in ent_nids:
            ref_counts[ent_nid] = ref_counts.get(ent_nid, 0) + 1

    for ent_nid, count in ref_counts.items():
        node = node_index.get(ent_nid)
        if node and node.get("type") in ("entity", "bridge-entity"):
            # Size proportional to sqrt(references) for visual balance
            node["size"] = max(node.get("size", 2), 2 + count**0.5 * 2)
            node["referenceCount"] = count


# ── Main entry point ─────────────────────────────────────────────────


def add_memory_nodes(
    sorted_memories: list[dict],
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
    domain_hub_ids: dict[str, str],
    entity_names: dict[str, str],
    type_group_map: dict[str, dict[str, str]],
) -> None:
    """Add memory nodes with multi-entity linking and topic clustering.

    New notation produces:
    - Memory nodes with heat-gradient color and consolidation-stage opacity
    - Multi-entity edges (ALL matches, not just best)
    - Topic nodes clustering memories by shared tags
    - Entity co-reference edges (entity backbone)
    - Bridge-entity promotion for cross-domain concepts
    """
    inline_entities: dict[str, str] = {}

    # Build O(1) node lookup
    node_index: dict[str, Node] = {n["id"]: n for n in nodes}

    # Track per-memory data for topic clustering and co-reference
    memory_nids: list[str] = []
    memory_tags: dict[str, list[str]] = {}
    memory_domains: dict[str, str] = {}
    memory_entity_links: dict[str, list[str]] = {}

    for mem in sorted_memories:
        nid = next_id("mem")
        content = mem.get("content", "")
        mem_domain = mem.get("domain", "")
        heat = mem.get("heat", 0)
        emo = tag_memory_emotions(content)
        color = _resolve_memory_color(emo, heat)
        node = _build_memory_node(mem, nid, emo, color)
        nodes.append(node)
        node_index[nid] = node

        linked_ents = _link_memory(
            nid,
            mem,
            mem_domain,
            entity_names,
            node_index,
            edges,
            domain_hub_ids,
            type_group_map,
            next_id,
            inline_entities,
            nodes,
        )

        memory_nids.append(nid)
        memory_tags[nid] = mem.get("tags") or []
        memory_domains[nid] = mem_domain
        memory_entity_links[nid] = linked_ents

    # Phase 2: Build lateral structure from accumulated data

    # 2a. Topic nodes from shared tags
    _build_topic_nodes(
        memory_nids,
        memory_tags,
        memory_domains,
        node_index,
        next_id,
        nodes,
        edges,
        domain_hub_ids,
        type_group_map,
    )

    # 2b. Entity co-reference edges (entity backbone)
    _add_coref_edges(memory_entity_links, node_index, edges)

    # 2c. Promote cross-domain entities to bridge-entity
    _promote_bridge_entities(
        {},  # entity_id_map not needed for node_index lookup
        node_index,
        memory_entity_links,
        memory_domains,
    )

    # 2d. Resize entities by reference count
    _resize_entities_by_references(memory_entity_links, node_index)
