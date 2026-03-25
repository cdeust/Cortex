"""Microglial pruning — complement-dependent synapse elimination.

Based on Wang et al. (Science, 2020): microglia mediate forgetting via
complement-dependent synaptic elimination. The brain actively removes
unused synapses to optimize memory storage and retrieval.

In Cortex: during consolidation, identify knowledge graph edges and entities
that are inactive and prune them. Uses "eat-me" / "don't-eat-me" signals
mapped to access patterns and protection status.

Eat-me signals (mark for pruning):
  - Edge weight below threshold
  - No recent co-activation
  - Both endpoints have low heat

Don't-eat-me signals (protect from pruning):
  - Entity is_protected flag
  - Edge recently strengthened (LTP)
  - Entity has high access_count
  - Entity appears in anchored memories

Pure business logic — no I/O.
"""

from __future__ import annotations

from typing import Any

# ── Defaults ──────────────────────────────────────────────────────────────

_MIN_EDGE_WEIGHT: float = 0.05  # Edges below this are candidates
_MIN_ENTITY_HEAT: float = 0.02  # Entities below this are candidates
_MIN_ACCESS_COUNT: int = 2  # Entities accessed fewer times are weak
_STALE_HOURS: float = 168.0  # 7 days without co-access = stale
_PROTECTION_ACCESS_THRESHOLD: int = 5  # High-access entities are protected


def _score_edge(
    edge: dict,
    entity_heat: dict[int, float],
    min_weight: float,
    stale_hours: float,
) -> list[str]:
    """Compute eat-me signal reasons for a single edge."""
    reasons = []
    if edge.get("weight", 1.0) < min_weight:
        reasons.append("low_weight")
    if edge.get("hours_since_co_access", 0) > stale_hours:
        reasons.append("stale")
    src_heat = entity_heat.get(edge["source_entity_id"], 0)
    tgt_heat = entity_heat.get(edge["target_entity_id"], 0)
    if src_heat < 0.1 and tgt_heat < 0.1:
        reasons.append("cold_endpoints")
    return reasons


def identify_prunable_edges(
    edges: list[dict[str, Any]],
    entity_heat: dict[int, float],
    entity_protected: dict[int, bool],
    min_weight: float = _MIN_EDGE_WEIGHT,
    stale_hours: float = _STALE_HOURS,
) -> list[dict[str, Any]]:
    """Identify edges to prune (≥2 eat-me signals, no don't-eat-me)."""
    prunable = []
    for edge in edges:
        src = edge["source_entity_id"]
        tgt = edge["target_entity_id"]
        if entity_protected.get(src, False) or entity_protected.get(tgt, False):
            continue
        reasons = _score_edge(edge, entity_heat, min_weight, stale_hours)
        if len(reasons) >= 2:
            prunable.append(
                {
                    **edge,
                    "prune_reason": reasons,
                }
            )

    return prunable


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
    """Compute pruning summary statistics.

    Returns
    -------
    Dict with counts, percentages, and per-reason breakdowns.
    """
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
