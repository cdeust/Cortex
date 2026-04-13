"""Unified graph builder — hierarchical tree visualization.

Builds a 6-level hierarchy:
  Root → Category → Project → Agent → Type-Group → Leaf

Thin orchestrator that composes node and edge builders into a single graph
payload for the unified 2D visualization. Pure business logic — no I/O.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.graph_builder_dedup import aggregate_domains
from mcp_server.core.graph_builder_edges import (
    add_bridge_edges,
    add_persistent_feature_edges,
    add_relationship_edges,
    apply_batch_pagination,
    build_clusters,
)
from mcp_server.core.graph_builder_memory import (
    add_entity_nodes,
    add_memory_nodes,
)
from mcp_server.core.graph_builder_nodes import (
    add_agent_node,
    add_behavioral_features,
    add_category_node,
    add_domain_hub,
    add_entry_points,
    add_recurring_patterns,
    add_root_node,
    add_tool_preferences,
    add_type_group_nodes,
    classify_tech_category,
)
from mcp_server.core.graph_quality_scorer import score_all_nodes
from mcp_server.infrastructure.agent_config import get_agents_for_project


def _filter_and_sort(
    items: list[dict],
    filter_domain: str | None,
    limit: int,
) -> list[dict]:
    """Sort by heat descending, optionally filter by domain, then cap."""
    result = sorted(items, key=lambda x: x.get("heat", 0), reverse=True)
    if filter_domain:
        result = [x for x in result if (x.get("domain") or "") == filter_domain]
    return result[:limit] if limit > 0 else result


def _build_entity_name_lookup(
    sorted_entities: list[dict],
    entity_id_map: dict[int, str],
) -> dict[str, str]:
    """Build lowercase entity name to node id mapping."""
    entity_names: dict[str, str] = {}
    for ent in sorted_entities:
        name = (ent.get("name") or "").lower()
        if len(name) > 2:
            db_id = ent.get("id")
            if db_id is not None and db_id in entity_id_map:
                entity_names[name] = entity_id_map[db_id]
    return entity_names


def _build_meta(
    type_counts: dict[str, int],
    total_nodes: int,
    total_edges: int,
    clusters: list,
    batch: int,
    batch_size: int,
    total_batches: int,
) -> dict[str, Any]:
    """Assemble the meta summary dict."""
    return {
        "domain_count": type_counts.get("domain", 0),
        "memory_count": type_counts.get("memory", 0),
        "entity_count": type_counts.get("entity", 0) + type_counts.get("bridge-entity", 0),
        "agent_count": type_counts.get("agent", 0),
        "category_count": type_counts.get("category", 0),
        "topic_count": type_counts.get("topic", 0),
        "bridge_entity_count": type_counts.get("bridge-entity", 0),
        "edge_count": total_edges,
        "cluster_count": len(clusters),
        "node_count": total_nodes,
        "type_counts": type_counts,
        "batch": batch,
        "batch_size": batch_size,
        "total_batches": total_batches,
    }


def _count_types(nodes: list[dict[str, Any]]) -> dict[str, int]:
    """Count nodes by type."""
    counts: dict[str, int] = {}
    for n in nodes:
        counts[n["type"]] = counts.get(n["type"], 0) + 1
    return counts


# ── Hierarchy builder ────────────────────────────────────────────────


def _build_hierarchy(
    profiles: dict,
    filter_domain: str | None,
    next_id: Any,
    nodes: list,
    edges: list,
    domain_hub_ids: dict[str, str],
) -> dict[str, dict[str, str]]:
    """Build the full 6-level tree. Returns type_group_map for memory linking.

    Returns:
        type_group_map: {domain_key: {"Memories": tg_id, "Tools": tg_id, ...}}
    """
    all_domains = profiles.get("domains") or {}
    aggregated = aggregate_domains(all_domains)

    if filter_domain:
        for gk, dp in aggregated.items():
            orig_keys = dp.get("_orig_keys", [gk])
            if filter_domain in orig_keys or filter_domain == gk:
                aggregated = {gk: dp}
                break
        else:
            aggregated = {}

    # Level 0: Root
    root_id = add_root_node(next_id, nodes)

    # Classify domains into categories
    category_members: dict[str, list[tuple[str, dict]]] = {}
    for domain_key, dp in aggregated.items():
        if not dp:
            continue
        cat = classify_tech_category(dp)
        category_members.setdefault(cat, []).append((domain_key, dp))

    # Level 1: Categories
    category_ids: dict[str, str] = {}
    for cat_name in category_members:
        category_ids[cat_name] = add_category_node(
            cat_name, root_id, next_id, nodes, edges
        )

    # Level 2-4: Projects → Agents → Type-Groups → Leaves
    type_group_map: dict[str, dict[str, str]] = {}

    for cat_name, members in category_members.items():
        cat_id = category_ids[cat_name]

        for domain_key, dp in members:
            # Level 2: Project
            hub_id = add_domain_hub(dp, domain_key, cat_id, next_id, nodes, edges)
            domain_hub_ids[domain_key] = hub_id
            for orig in dp.get("_orig_keys", []):
                domain_hub_ids[orig] = hub_id
            # Also register kebab-case variant so DB memory domains match
            kebab = domain_key.replace(" ", "-").lower()
            if kebab != domain_key:
                domain_hub_ids[kebab] = hub_id

            # Level 3: Agents for this project
            agents = get_agents_for_project(domain_key)
            if agents:
                # Each agent gets its own type-groups
                all_tg: dict[str, str] = {}
                for agent_def in agents:
                    agent_id = add_agent_node(
                        agent_def, domain_key, hub_id, next_id, nodes, edges
                    )
                    tg = add_type_group_nodes(
                        agent_id, domain_key, next_id, nodes, edges
                    )
                    # Merge — first agent's type-group wins for shared keys
                    for label, tg_id in tg.items():
                        if label not in all_tg:
                            all_tg[label] = tg_id
                type_group_map[domain_key] = all_tg
            else:
                # No agents defined: create type-groups directly under project
                tg = add_type_group_nodes(hub_id, domain_key, next_id, nodes, edges)
                type_group_map[domain_key] = tg

            # Level 5: Leaf nodes into type-groups
            tg_map = type_group_map[domain_key]
            add_entry_points(
                dp,
                domain_key,
                tg_map.get("Entry Points", hub_id),
                next_id,
                nodes,
                edges,
            )
            add_recurring_patterns(
                dp,
                domain_key,
                tg_map.get("Patterns", hub_id),
                next_id,
                nodes,
                edges,
            )
            add_tool_preferences(
                dp,
                domain_key,
                tg_map.get("Tools", hub_id),
                next_id,
                nodes,
                edges,
            )
            add_behavioral_features(
                dp,
                domain_key,
                tg_map.get("Features", hub_id),
                next_id,
                nodes,
                edges,
            )

            # Cross-domain edges
            add_bridge_edges(
                dp,
                hub_id,
                list(aggregated.keys()),
                domain_hub_ids,
                edges,
            )

    add_persistent_feature_edges(profiles, domain_hub_ids, edges)
    return type_group_map


# ── ID allocator ─────────────────────────────────────────────────────


def _make_id_allocator() -> tuple[Any, ...]:
    """Create a node ID allocator."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    domain_hub_ids: dict[str, str] = {}
    entity_id_map: dict[int, str] = {}
    counter = [0]

    def next_id(prefix: str) -> str:
        counter[0] += 1
        return f"{prefix}_{counter[0]}"

    return next_id, nodes, edges, domain_hub_ids, entity_id_map


# ── Memory and entity nodes ─────────────────────────────────────────


def _add_memory_and_entity_nodes(
    entities: list[dict],
    memories: list[dict],
    relationships: list[dict],
    filter_domain: str | None,
    max_memories: int,
    max_entities: int,
    next_id: Any,
    nodes: list,
    edges: list,
    domain_hub_ids: dict[str, str],
    entity_id_map: dict[int, str],
    type_group_map: dict[str, dict[str, str]],
) -> None:
    """Add entity and memory nodes to the graph."""
    sorted_entities = _filter_and_sort(entities, filter_domain, max_entities)
    add_entity_nodes(
        sorted_entities,
        next_id,
        nodes,
        edges,
        domain_hub_ids,
        entity_id_map,
        type_group_map,
    )
    add_relationship_edges(relationships, entity_id_map, edges)

    # Remove orphan entity nodes (zero edges after filtering)
    connected_ids: set[str] = set()
    for e in edges:
        connected_ids.add(e["source"] if isinstance(e["source"], str) else e["source"]["id"])
        connected_ids.add(e["target"] if isinstance(e["target"], str) else e["target"]["id"])
    nodes[:] = [
        n for n in nodes
        if n["type"] != "entity" or n["id"] in connected_ids
    ]

    sorted_memories = _filter_and_sort(memories, filter_domain, max_memories)
    entity_names = _build_entity_name_lookup(sorted_entities, entity_id_map)
    add_memory_nodes(
        sorted_memories,
        next_id,
        nodes,
        edges,
        domain_hub_ids,
        entity_names,
        type_group_map,
    )


# ── Graph population ─────────────────────────────────────────────────


def _populate_graph(
    profiles: dict,
    memories: list[dict],
    entities: list[dict],
    relationships: list[dict],
    filter_domain: str | None,
    max_memories: int,
    max_entities: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """Populate nodes and edges from all data sources."""
    next_id, nodes, edges, domain_hub_ids, entity_id_map = _make_id_allocator()

    type_group_map = _build_hierarchy(
        profiles, filter_domain, next_id, nodes, edges, domain_hub_ids
    )
    _add_memory_and_entity_nodes(
        entities,
        memories,
        relationships,
        filter_domain,
        max_memories,
        max_entities,
        next_id,
        nodes,
        edges,
        domain_hub_ids,
        entity_id_map,
        type_group_map,
    )
    score_all_nodes(nodes, edges)
    _mark_collapsed_leaves(nodes, edges)
    return nodes, edges, domain_hub_ids


# ── Progressive disclosure collapse ────────────────────────────────

# Node types that form the visible skeleton — never collapse them.
_STRUCTURAL_TYPES = {
    "root", "category", "domain", "agent", "type-group", "topic", "bridge-entity",
}

# Types always collapsed into a parent for progressive disclosure.
# Only entities are collapsed — memories ARE the content and must be visible.
_ALWAYS_COLLAPSE_TYPES = {"entity"}

# Types collapsed only when degree-1 (low-cardinality, useful visible).
_DEGREE1_COLLAPSE_TYPES = {
    "entry-point",
    "recurring-pattern",
    "tool-preference",
    "behavioral-feature",
}

# Priority order for choosing the best parent among neighbors.
# Lower index = preferred parent. Topic > type-group > domain > anything.
_PARENT_PRIORITY = {
    "topic": 0,
    "type-group": 1,
    "domain": 2,
    "agent": 3,
    "category": 4,
    "bridge-entity": 5,
    "root": 6,
}


def _mark_collapsed_leaves(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    """Collapse nodes for progressive disclosure — readable graph at a glance.

    Two-tier strategy:
    1. Memory and entity nodes are ALWAYS collapsed into their best parent
       (topic > type-group > domain), regardless of degree. This is what
       takes the graph from 1887 unreadable nodes to ~200 visible landmarks.
    2. Methodology leaf nodes (entry-points, patterns, tools, features) are
       collapsed only when degree-1 (same as before).

    The visible graph shows: root, categories, domains, agents, type-groups,
    topics, and bridge-entities. Individual memories appear on click/expand.

    Nodes with ``collapsed=True`` carry their parent id in ``_parentId``.
    Parent nodes receive ``_childCount`` (total hidden children) and
    ``_collapsedChildren`` (list of collapsed child node dicts).
    """
    node_index: dict[str, dict[str, Any]] = {n["id"]: n for n in nodes}

    # Build adjacency: node_id -> [(neighbor_id, edge_type, edge_weight)]
    adjacency: dict[str, list[tuple[str, str, float]]] = {n["id"]: [] for n in nodes}
    for e in edges:
        src = e["source"] if isinstance(e["source"], str) else e["source"]["id"]
        tgt = e["target"] if isinstance(e["target"], str) else e["target"]["id"]
        etype = e.get("type", "default")
        weight = e.get("weight", 0.3)
        if src in adjacency:
            adjacency[src].append((tgt, etype, weight))
        if tgt in adjacency:
            adjacency[tgt].append((src, etype, weight))

    # Assign each collapsible node to its best parent.
    collapse_map: dict[str, str] = {}  # node_id -> parent_id

    for n in nodes:
        nid = n["id"]
        ntype = n["type"]
        neighbors = adjacency.get(nid, [])
        degree = len(neighbors)

        # Tier 1: always collapse memory/entity nodes
        if ntype in _ALWAYS_COLLAPSE_TYPES:
            parent_id = _best_parent(nid, neighbors, node_index)
            if parent_id:
                collapse_map[nid] = parent_id
            else:
                # No parent found — orphan. Mark collapsed with no parent
                # so it's hidden but not assigned to any expandable group.
                n["collapsed"] = True
            continue

        # Tier 2: collapse degree-1 methodology leaves
        if ntype in _DEGREE1_COLLAPSE_TYPES and degree == 1:
            collapse_map[nid] = neighbors[0][0]
            continue

        # Tier 3: collapse type-groups with no visible children
        # (all their children were collapsed in tier 1)
        if ntype == "type-group" and degree <= 1:
            if neighbors:
                collapse_map[nid] = neighbors[0][0]
            else:
                n["collapsed"] = True

    # Tag collapsed nodes and build parent metadata.
    parent_children: dict[str, list[dict[str, Any]]] = {}
    for child_id, parent_id in collapse_map.items():
        node_index[child_id]["collapsed"] = True
        node_index[child_id]["_parentId"] = parent_id
        parent_children.setdefault(parent_id, []).append(node_index[child_id])

    for parent_id, children in parent_children.items():
        if parent_id in node_index:
            node_index[parent_id]["_childCount"] = len(children)
            # Include minimal child info for frontend expansion.
            node_index[parent_id]["_collapsedChildren"] = [
                {
                    "id": c["id"],
                    "type": c["type"],
                    "label": c.get("label", ""),
                    "color": c.get("color", "#50C8E0"),
                    "size": c.get("size", 2),
                    "heat": c.get("heat", 0),
                    "content": (c.get("content", "") or "")[:120],
                }
                for c in children
            ]


def _best_parent(
    node_id: str,
    neighbors: list[tuple[str, str, float]],
    node_index: dict[str, dict[str, Any]],
) -> str | None:
    """Choose the best parent for a collapsible node.

    Prefers: topic > type-group > domain > agent > category > bridge-entity.
    Among same-priority parents, picks the one with highest edge weight.
    """
    best_id: str | None = None
    best_priority = 999
    best_weight = -1.0

    for neighbor_id, _etype, weight in neighbors:
        neighbor = node_index.get(neighbor_id)
        if not neighbor:
            continue
        priority = _PARENT_PRIORITY.get(neighbor["type"], 10)
        if priority < best_priority or (
            priority == best_priority and weight > best_weight
        ):
            best_id = neighbor_id
            best_priority = priority
            best_weight = weight

    return best_id


# ── Final assembly ───────────────────────────────────────────────────


def _build_and_paginate(
    nodes: list,
    edges: list,
    domain_hub_ids: dict[str, str],
    batch: int,
    batch_size: int,
) -> dict[str, Any]:
    """Cluster, paginate, and assemble the final graph payload."""
    clusters = build_clusters(nodes, domain_hub_ids)
    type_counts = _count_types(nodes)
    total_nodes, total_edges = len(nodes), len(edges)

    nodes, edges, clusters, total_batches = apply_batch_pagination(
        nodes,
        edges,
        clusters,
        batch,
        batch_size,
    )
    meta = _build_meta(
        type_counts,
        total_nodes,
        total_edges,
        clusters,
        batch,
        batch_size,
        total_batches,
    )
    meta["benchmarks"] = {
        "LongMemEval": {"recall_10": 97.0, "mrr": 0.855, "paper_best": 78.4},
        "LoCoMo": {"recall_10": 84.4, "mrr": 0.599, "paper_best": 50.0},
        "BEAM": {"recall_10": 67.5, "mrr": 0.517, "paper_best": 32.9},
    }
    return {"nodes": nodes, "edges": edges, "clusters": clusters, "meta": meta}


def build_unified_graph(
    profiles: dict | None = None,
    memories: list[dict] | None = None,
    entities: list[dict] | None = None,
    relationships: list[dict] | None = None,
    filter_domain: str | None = None,
    max_memories: int = 0,
    max_entities: int = 0,
    batch: int = 0,
    batch_size: int = 0,
) -> dict[str, Any]:
    """Build a unified hierarchical graph combining all data sources."""
    profiles = profiles or {}
    nodes, edges, domain_hub_ids = _populate_graph(
        profiles,
        memories or [],
        entities or [],
        relationships or [],
        filter_domain,
        max_memories,
        max_entities,
    )
    return _build_and_paginate(nodes, edges, domain_hub_ids, batch, batch_size)
