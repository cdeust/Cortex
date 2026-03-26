"""Unified graph builder — merges methodology profiles + memory + knowledge graph.

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
    add_behavioral_features,
    add_entry_points,
    add_recurring_patterns,
    add_tool_preferences,
    add_domain_hub,
)
from mcp_server.core.graph_quality_scorer import score_all_nodes


def _filter_and_sort(
    items: list[dict],
    filter_domain: str | None,
    limit: int,
) -> list[dict]:
    """Sort by heat descending, optionally filter by domain, then cap."""
    result = sorted(items, key=lambda x: x.get("heat", 0), reverse=True)
    if filter_domain:
        result = [x for x in result if (x.get("domain") or "") == filter_domain]
    return result[:limit]


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
        "entity_count": type_counts.get("entity", 0),
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


def _add_domain_profiles(
    profiles: dict,
    filter_domain: str | None,
    next_id,
    nodes: list,
    edges: list,
    domain_hub_ids: dict[str, str],
) -> list[str]:
    """Process all domain profiles, returning the list of domain keys."""
    all_domains = profiles.get("domains") or {}

    # Aggregate similar domains to prevent duplication
    aggregated = aggregate_domains(all_domains)

    if filter_domain:
        # Find the group key that contains this domain
        for gk, dp in aggregated.items():
            orig_keys = dp.get("_orig_keys", [gk])
            if filter_domain in orig_keys or filter_domain == gk:
                aggregated = {gk: dp}
                break
        else:
            aggregated = {}

    domain_keys = list(aggregated.keys())

    for domain_key, dp in aggregated.items():
        if not dp:
            continue
        hub_id = add_domain_hub(dp, domain_key, next_id, nodes)
        domain_hub_ids[domain_key] = hub_id

        # Also map original keys to this hub for edge lookups
        for orig in dp.get("_orig_keys", []):
            domain_hub_ids[orig] = hub_id

        add_entry_points(dp, domain_key, hub_id, next_id, nodes, edges)
        add_recurring_patterns(dp, domain_key, hub_id, next_id, nodes, edges)
        add_tool_preferences(dp, domain_key, hub_id, next_id, nodes, edges)
        add_behavioral_features(dp, domain_key, hub_id, next_id, nodes, edges)
        add_bridge_edges(dp, hub_id, domain_keys, domain_hub_ids, edges)

    add_persistent_feature_edges(profiles, domain_hub_ids, edges)
    return domain_keys


def _make_id_allocator() -> tuple[Any, ...]:
    """Create a node ID allocator. Returns (next_id_fn, nodes, edges, hub_ids, ent_map)."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    domain_hub_ids: dict[str, str] = {}
    entity_id_map: dict[int, str] = {}
    counter = [0]

    def next_id(prefix: str) -> str:
        counter[0] += 1
        return f"{prefix}_{counter[0]}"

    return next_id, nodes, edges, domain_hub_ids, entity_id_map


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
) -> None:
    """Add entity and memory nodes to the graph."""
    sorted_entities = _filter_and_sort(entities, filter_domain, max_entities)
    add_entity_nodes(
        sorted_entities, next_id, nodes, edges, domain_hub_ids, entity_id_map
    )
    add_relationship_edges(relationships, entity_id_map, edges)
    sorted_memories = _filter_and_sort(memories, filter_domain, max_memories)
    entity_names = _build_entity_name_lookup(sorted_entities, entity_id_map)
    add_memory_nodes(
        sorted_memories, next_id, nodes, edges, domain_hub_ids, entity_names
    )


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

    _add_domain_profiles(profiles, filter_domain, next_id, nodes, edges, domain_hub_ids)
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
    )
    score_all_nodes(nodes, edges)
    return nodes, edges, domain_hub_ids


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
    max_memories: int = 200,
    max_entities: int = 100,
    batch: int = 0,
    batch_size: int = 0,
) -> dict[str, Any]:
    """Build a unified graph combining all data sources."""
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
