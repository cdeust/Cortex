"""Knowledge graph pruning via disparity filter and orphan detection.

Edge pruning uses the multiscale backbone extraction algorithm from:
  Serrano MA, Boguna M, Vespignani A (2009) "Extracting the multiscale
  backbone of complex weighted networks." PNAS 106(16):6483-6488.

For each edge (i,j) with weight w_ij, the disparity filter computes a
p-value alpha_ij = (1 - p_ij)^{k_i - 1} where p_ij = w_ij / strength(i).
Edges kept when alpha < threshold at EITHER endpoint (statistically
significant at either end).

Temporal decay follows Aggarwal & Subbian (2014): effective weight decays
exponentially with hours since last co-access, half-life = 168h (7 days).

Pure business logic -- no I/O.
"""

from __future__ import annotations

import math
from typing import Any

# -- Defaults ----------------------------------------------------------------

_ALPHA_THRESHOLD: float = 0.05  # Standard significance level (Serrano 2009)
_TEMPORAL_HALF_LIFE_HOURS: float = 168.0  # 7 days (Aggarwal & Subbian 2014)
_MIN_ENTITY_HEAT: float = 0.02
_MIN_ACCESS_COUNT: int = 2
_PROTECTION_ACCESS_THRESHOLD: int = 5


def _temporal_decay(hours: float, half_life: float) -> float:
    """Exponential temporal decay: exp(-lambda * hours).

    lambda = ln(2) / half_life so that weight halves every half_life hours.
    Aggarwal & Subbian (2014).
    """
    if hours <= 0:
        return 1.0
    lam = math.log(2) / half_life
    return math.exp(-lam * hours)


def _build_adjacency(
    edges: list[dict[str, Any]],
    half_life: float,
) -> tuple[dict[int, dict[int, float]], dict[int, float], dict[int, int]]:
    """Build adjacency with temporally-decayed effective weights.

    Returns (adj, strength, degree) where:
      adj[i][j] = w_effective for edge i-j
      strength[i] = sum of effective weights at node i
      degree[i] = number of edges at node i
    """
    adj: dict[int, dict[int, float]] = {}
    for edge in edges:
        src = edge["source_entity_id"]
        tgt = edge["target_entity_id"]
        raw_w = edge.get("weight", 1.0)
        hours = edge.get("hours_since_co_access", 0)
        w_eff = raw_w * _temporal_decay(hours, half_life)

        adj.setdefault(src, {})[tgt] = w_eff
        adj.setdefault(tgt, {})[src] = w_eff

    strength: dict[int, float] = {}
    degree: dict[int, int] = {}
    for node, neighbors in adj.items():
        strength[node] = sum(neighbors.values())
        degree[node] = len(neighbors)

    return adj, strength, degree


def _disparity_alpha(p: float, k: int) -> float:
    """Compute disparity filter p-value: alpha = (1 - p)^{k - 1}.

    Serrano et al. (2009) Eq. 2. Under the null hypothesis of uniform
    weight distribution across k edges, alpha is the probability of
    observing a normalized weight >= p.

    For k <= 1, every edge is significant (alpha = 0).
    """
    if k <= 1:
        return 0.0
    return (1.0 - p) ** (k - 1)


def identify_prunable_edges(
    edges: list[dict[str, Any]],
    entity_heat: dict[int, float],
    entity_protected: dict[int, bool],
    alpha_threshold: float = _ALPHA_THRESHOLD,
    half_life: float = _TEMPORAL_HALF_LIFE_HOURS,
) -> list[dict[str, Any]]:
    """Identify edges to prune via Serrano et al. (2009) disparity filter.

    Steps:
      1. Apply temporal decay to raw weights (Aggarwal & Subbian 2014).
      2. For each edge, compute disparity alpha at both endpoints.
      3. Keep edge if alpha < threshold at EITHER endpoint.
      4. Never prune edges touching protected entities.

    Returns list of edge dicts augmented with prune_reason metadata.
    """
    from mcp_server.core.ablation import Mechanism, is_mechanism_disabled

    if is_mechanism_disabled(Mechanism.MICROGLIAL_PRUNING):
        # No-op: never prune edges.
        return []
    if not edges:
        return []

    adj, strength, degree = _build_adjacency(edges, half_life)

    prunable = []
    for edge in edges:
        src = edge["source_entity_id"]
        tgt = edge["target_entity_id"]

        if entity_protected.get(src, False) or entity_protected.get(tgt, False):
            continue

        w_eff = adj.get(src, {}).get(tgt, 0.0)
        s_src = strength.get(src, 0.0)
        s_tgt = strength.get(tgt, 0.0)
        k_src = degree.get(src, 0)
        k_tgt = degree.get(tgt, 0)

        p_src = w_eff / s_src if s_src > 0 else 1.0
        p_tgt = w_eff / s_tgt if s_tgt > 0 else 1.0

        alpha_src = _disparity_alpha(p_src, k_src)
        alpha_tgt = _disparity_alpha(p_tgt, k_tgt)

        significant = alpha_src < alpha_threshold or alpha_tgt < alpha_threshold
        if significant:
            continue

        reasons = _classify_prune_reasons(edge, entity_heat, alpha_src, alpha_tgt)
        prunable.append({**edge, "prune_reason": reasons})

    return prunable


def _classify_prune_reasons(
    edge: dict,
    entity_heat: dict[int, float],
    alpha_src: float,
    alpha_tgt: float,
) -> list[str]:
    """Classify why an edge was pruned for diagnostic reporting."""
    reasons = ["disparity_insignificant"]
    if edge.get("hours_since_co_access", 0) > _TEMPORAL_HALF_LIFE_HOURS:
        reasons.append("stale")
    src_heat = entity_heat.get(edge["source_entity_id"], 0)
    tgt_heat = entity_heat.get(edge["target_entity_id"], 0)
    if src_heat < 0.1 and tgt_heat < 0.1:
        reasons.append("cold_endpoints")
    return reasons


# -- Orphan detection (unchanged) -------------------------------------------


def _is_orphan_candidate(
    ent: dict, edge_ids: set[int], mem_ids: set[int], min_heat: float, min_access: int
) -> bool:
    """Check if entity passes all orphan criteria."""
    if ent.get("is_protected", False):
        return False
    if ent.get("access_count", 0) >= _PROTECTION_ACCESS_THRESHOLD:
        return False
    if ent["id"] in edge_ids or ent["id"] in mem_ids:
        return False
    if ent.get("heat", 0) >= min_heat:
        return False
    return ent.get("access_count", 0) < min_access


def identify_orphaned_entities(
    entities: list[dict[str, Any]],
    edge_entity_ids: set[int],
    memory_entity_ids: set[int],
    min_heat: float = _MIN_ENTITY_HEAT,
    min_access_count: int = _MIN_ACCESS_COUNT,
) -> list[dict[str, Any]]:
    """Identify entities to archive (disconnected, cold, low-access)."""
    return [
        {**ent, "archive_reason": ["orphaned", "cold", "low_access"]}
        for ent in entities
        if _is_orphan_candidate(
            ent, edge_entity_ids, memory_entity_ids, min_heat, min_access_count
        )
    ]


def compute_pruning_stats(
    prunable_edges: list[dict],
    orphaned_entities: list[dict],
    total_edges: int,
    total_entities: int,
) -> dict[str, Any]:
    """Compute pruning summary statistics."""
    edge_reasons: dict[str, int] = {}
    for e in prunable_edges:
        for r in e.get("prune_reason", []):
            edge_reasons[r] = edge_reasons.get(r, 0) + 1

    return {
        "edges_to_prune": len(prunable_edges),
        "entities_to_archive": len(orphaned_entities),
        "total_edges": total_edges,
        "total_entities": total_entities,
        "edge_prune_pct": round(len(prunable_edges) / max(total_edges, 1) * 100, 1),
        "entity_archive_pct": round(
            len(orphaned_entities) / max(total_entities, 1) * 100, 1
        ),
        "edge_reasons": edge_reasons,
    }
