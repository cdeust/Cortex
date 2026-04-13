"""Edge construction helpers for the unified graph builder.

Handles cross-domain bridges, persistent features, knowledge-graph
relationships, cluster assembly, and batch pagination. Pure logic — no I/O.
"""

from __future__ import annotations

from typing import Any

# ── Colors ────────────────────────────────────────────────────────────────

DOMAIN_COLOR = "#6366f1"

EDGE_COLORS = {
    "bridge": "#FF00FF",
    "persistent-feature": "#ec4899",
    "co_occurrence": "#d946ef",
    "imports": "#3b82f6",
    "calls": "#22d3ee",
    "caused_by": "#ff4444",
    "resolved_by": "#22c55e",
    "decided_to_use": "#f59e0b",
    "debugged_with": "#ef4444",
    "preceded_by": "#94a3b8",
    "derived_from": "#a78bfa",
    "domain-contains": "#06b6d4",
    "topic-member": "#06b6d480",
    "co-entity": "#a78bfa",
}

PERSISTENT_COLOR = "#ec4899"

Node = dict[str, Any]
Edge = dict[str, Any]


# ── Bridge edges ──────────────────────────────────────────────────────────


def add_bridge_edges(
    dp: dict,
    hub_id: str,
    domain_keys: list[str],
    domain_hub_ids: dict[str, str],
    edges: list[Edge],
) -> None:
    """Add bridge edges connecting this domain to other domains."""
    for bridge in dp.get("connectionBridges") or []:
        to_domain = bridge.get("toDomain")
        if to_domain in domain_keys and to_domain in domain_hub_ids:
            edges.append(
                {
                    "source": hub_id,
                    "target": domain_hub_ids[to_domain],
                    "type": "bridge",
                    "weight": bridge.get("weight") or 0.5,
                    "color": EDGE_COLORS["bridge"],
                    "label": bridge.get("pattern"),
                }
            )


# ── Persistent feature edges ─────────────────────────────────────────────


def add_persistent_feature_edges(
    profiles: dict,
    domain_hub_ids: dict[str, str],
    edges: list[Edge],
) -> None:
    """Add edges for behavioral features that persist across domains.

    Deduplicates: one edge per domain pair with aggregated weight and count.
    """
    pair_data: dict[tuple[str, str], dict] = {}
    for pf in profiles.get("persistentFeatures") or []:
        pf_domains = pf.get("domains") or []
        for i in range(len(pf_domains)):
            for j in range(i + 1, len(pf_domains)):
                src = domain_hub_ids.get(pf_domains[i])
                tgt = domain_hub_ids.get(pf_domains[j])
                if src and tgt and src != tgt:
                    key = (min(src, tgt), max(src, tgt))
                    if key not in pair_data:
                        pair_data[key] = {"weight": 0, "count": 0, "labels": []}
                    pair_data[key]["weight"] += pf.get("persistence", 0)
                    pair_data[key]["count"] += 1
                    label = pf.get("label", "")
                    if label and len(pair_data[key]["labels"]) < 3:
                        pair_data[key]["labels"].append(label)

    for (src, tgt), info in pair_data.items():
        edges.append(
            {
                "source": src,
                "target": tgt,
                "type": "persistent-feature",
                "weight": min(info["weight"] / max(info["count"], 1), 1.0),
                "color": PERSISTENT_COLOR,
                "label": f"{info['count']} shared features",
            }
        )


# ── Knowledge graph relationships ─────────────────────────────────────────


def add_relationship_edges(
    relationships: list[dict],
    entity_id_map: dict[int, str],
    edges: list[Edge],
) -> None:
    """Add edges from knowledge-graph relationships between entities.

    Excludes co_occurrence relationships from visualization — they represent
    extraction coincidence (96% of all edges), not semantic structure.
    Only co_retrieval, derived_from, and other curated types are shown.
    """
    for rel in relationships:
        rel_type = rel.get("relationship_type") or rel.get("type", "related")
        if rel_type == "co_occurrence":
            continue

        src_db_id = rel.get("source_entity_id") or rel.get("source")
        tgt_db_id = rel.get("target_entity_id") or rel.get("target")
        src_nid = entity_id_map.get(src_db_id)
        tgt_nid = entity_id_map.get(tgt_db_id)
        if not src_nid or not tgt_nid or src_nid == tgt_nid:
            continue

        edges.append(
            {
                "source": src_nid,
                "target": tgt_nid,
                "type": rel_type,
                "weight": rel.get("weight", 0.5),
                "color": EDGE_COLORS.get(rel_type, "#90a4ae"),
                "isCausal": bool(rel.get("is_causal", False)),
            }
        )


# ── Cluster assembly ─────────────────────────────────────────────────────


def build_clusters(
    nodes: list[Node],
    domain_hub_ids: dict[str, str],
) -> list[dict[str, Any]]:
    """Group nodes by domain into L1 clusters."""
    domain_groups: dict[str, list[str]] = {}
    for node in nodes:
        grp = node.get("group", "_ungrouped")
        domain_groups.setdefault(grp, []).append(node["id"])

    clusters: list[dict[str, Any]] = []
    for grp_key, member_ids in domain_groups.items():
        if len(member_ids) < 2:
            continue
        hub_color = DOMAIN_COLOR
        if grp_key in domain_hub_ids:
            hub_node = next(
                (n for n in nodes if n["id"] == domain_hub_ids[grp_key]), None
            )
            if hub_node:
                hub_color = hub_node.get("color", DOMAIN_COLOR)
        clusters.append(
            {
                "id": f"cluster_{grp_key}",
                "level": "l1",
                "member_ids": member_ids,
                "domain": grp_key,
                "color": hub_color,
                "label": grp_key,
            }
        )
    return clusters


# ── Batch pagination ──────────────────────────────────────────────────────


def apply_batch_pagination(
    nodes: list[Node],
    edges: list[Edge],
    clusters: list[dict[str, Any]],
    batch: int,
    batch_size: int,
) -> tuple[list[Node], list[Edge], list[dict[str, Any]], int]:
    """Slice nodes/edges into batches. Returns (nodes, edges, clusters, total_batches)."""
    if batch_size <= 0 or len(nodes) == 0:
        return nodes, edges, clusters, 1

    _SKELETON_TYPES = {"root", "category", "domain", "agent", "type-group"}
    skeleton_nodes = [n for n in nodes if n["type"] in _SKELETON_TYPES]
    child_nodes = [n for n in nodes if n["type"] not in _SKELETON_TYPES]
    skeleton_ids = {n["id"] for n in skeleton_nodes}
    total_batches = max(1, -(-len(child_nodes) // batch_size))

    if batch == 0:
        filtered_edges = [
            e
            for e in edges
            if e["source"] in skeleton_ids and e["target"] in skeleton_ids
        ]
        return skeleton_nodes, filtered_edges, clusters, total_batches

    page_start = (batch - 1) * batch_size
    page_nodes = child_nodes[page_start : page_start + batch_size]
    page_ids = {n["id"] for n in page_nodes}
    allowed_ids = page_ids | skeleton_ids
    filtered_edges = [
        e
        for e in edges
        if (e["source"] in page_ids or e["target"] in page_ids)
        and e["source"] in allowed_ids
        and e["target"] in allowed_ids
    ]
    return page_nodes, filtered_edges, [], total_batches
