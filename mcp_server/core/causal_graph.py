"""Causal graph -- PC algorithm for causal edge discovery (Spirtes & Glymour 1991).

Adjacency matrix representation, no networkx. Pure business logic -- no I/O.
"""

from __future__ import annotations

import math
from typing import Any


def compute_co_occurrence_matrix(
    memories: list[dict[str, Any]],
    entity_names: list[str],
) -> dict[tuple[str, str], int]:
    """Count co-occurrences of entity pairs across memories.

    Returns {(entity_a, entity_b): count}.
    """
    counts: dict[tuple[str, str], int] = {}
    for mem in memories:
        content = (mem.get("content") or "").lower()
        present = [e for e in entity_names if e.lower() in content]

        for i in range(len(present)):
            for j in range(i + 1, len(present)):
                a, b = sorted([present[i], present[j]])
                key = (a, b)
                counts[key] = counts.get(key, 0) + 1

    return counts


def compute_conditional_independence(
    pair_count: int,
    a_count: int,
    b_count: int,
    total: int,
    conditioned_count: int = 0,
) -> float:
    """Test conditional independence using pointwise mutual information.

    High (>0) = dependent, low (<=0) = independent or negative.
    conditioned_count adjusts for a third variable explaining co-occurrence.
    """
    if total == 0 or a_count == 0 or b_count == 0:
        return 0.0

    p_ab = pair_count / total
    p_a = a_count / total
    p_b = b_count / total
    expected = p_a * p_b

    if expected == 0:
        return 0.0

    # Pointwise mutual information
    pmi = math.log2(p_ab / expected) if p_ab > 0 else -10.0

    # Adjust for conditioning
    if conditioned_count > 0:
        # If conditioning explains the co-occurrence, reduce PMI
        conditioning_ratio = conditioned_count / pair_count if pair_count > 0 else 0
        pmi *= max(0, 1.0 - conditioning_ratio)

    return round(pmi, 4)


def compute_temporal_precedence(
    entity_first_seen: dict[str, str],
    entity_a: str,
    entity_b: str,
) -> str | None:
    """Determine temporal ordering between two entities.

    Returns:
      - "a_before_b" if A consistently appears before B
      - "b_before_a" if B consistently appears before A
      - None if no clear ordering
    """
    time_a = entity_first_seen.get(entity_a)
    time_b = entity_first_seen.get(entity_b)

    if time_a is None or time_b is None:
        return None

    if time_a < time_b:
        return "a_before_b"
    elif time_b < time_a:
        return "b_before_a"
    return None


def _build_skeleton(
    co_occurrences: dict[tuple[str, str], int],
    entity_counts: dict[str, int],
    total_memories: int,
    independence_threshold: float,
    min_observations: int,
) -> dict[tuple[str, str], float]:
    """Build initial skeleton of dependent pairs via PMI filtering."""
    skeleton: dict[tuple[str, str], float] = {}

    for (a, b), count in co_occurrences.items():
        if count < min_observations:
            continue

        pmi = compute_conditional_independence(
            count, entity_counts.get(a, 0), entity_counts.get(b, 0), total_memories
        )

        if pmi > independence_threshold:
            skeleton[(a, b)] = pmi

    return skeleton


def _find_conditionally_independent_edges(
    skeleton: dict[tuple[str, str], float],
    entity_names: list[str],
    co_occurrences: dict[tuple[str, str], int],
    entity_counts: dict[str, int],
    total_memories: int,
    independence_threshold: float,
) -> set[tuple[str, str]]:
    """Test each skeleton edge for conditional independence given a third entity."""
    edges_to_remove: set[tuple[str, str]] = set()

    for a, b in skeleton:
        for c in entity_names:
            if c == a or c == b:
                continue

            ac_count = co_occurrences.get(tuple(sorted([a, c])), 0)
            bc_count = co_occurrences.get(tuple(sorted([b, c])), 0)

            if ac_count == 0 or bc_count == 0:
                continue

            min_with_c = min(ac_count, bc_count)
            ab_count = co_occurrences.get((a, b), 0)

            conditioned_pmi = compute_conditional_independence(
                ab_count,
                entity_counts.get(a, 0),
                entity_counts.get(b, 0),
                total_memories,
                conditioned_count=min_with_c,
            )

            if conditioned_pmi <= independence_threshold:
                edges_to_remove.add((a, b))
                break

    return edges_to_remove


def _orient_edges(
    skeleton: dict[tuple[str, str], float],
    co_occurrences: dict[tuple[str, str], int],
    entity_first_seen: dict[str, str],
) -> list[dict[str, Any]]:
    """Orient skeleton edges using temporal precedence."""
    causal_edges: list[dict[str, Any]] = []

    for (a, b), strength in skeleton.items():
        direction = compute_temporal_precedence(entity_first_seen, a, b)

        if direction == "a_before_b":
            source, target = a, b
        elif direction == "b_before_a":
            source, target = b, a
        else:
            source, target = a, b
            strength *= 0.5

        causal_edges.append(
            {
                "source": source,
                "target": target,
                "strength": round(strength, 4),
                "is_directed": direction is not None,
                "evidence": co_occurrences.get((a, b), 0),
            }
        )

    causal_edges.sort(key=lambda e: e["strength"], reverse=True)
    return causal_edges


def _prune_skeleton(
    skeleton: dict[tuple[str, str], float],
    edges_to_remove: set[tuple[str, str]],
) -> None:
    """Remove conditionally independent edges from the skeleton in place."""
    for edge in edges_to_remove:
        skeleton.pop(edge, None)


def discover_causal_edges(
    entity_names: list[str],
    co_occurrences: dict[tuple[str, str], int],
    entity_counts: dict[str, int],
    total_memories: int,
    entity_first_seen: dict[str, str] | None = None,
    independence_threshold: float = 0.5,
    min_observations: int = 3,
) -> list[dict[str, Any]]:
    """Simplified PC algorithm for causal edge discovery.

    Algorithm:
      1. Start with all edges where PMI > threshold (dependent pairs)
      2. For each edge, test conditional independence given each other entity
      3. Remove edges that become independent when conditioned
      4. Orient remaining edges using temporal precedence

    Returns list of causal edges: {source, target, strength, direction, evidence}.
    """
    if not entity_names or total_memories == 0:
        return []

    skeleton = _build_skeleton(
        co_occurrences,
        entity_counts,
        total_memories,
        independence_threshold,
        min_observations,
    )
    _prune_skeleton(
        skeleton,
        _find_conditionally_independent_edges(
            skeleton,
            entity_names,
            co_occurrences,
            entity_counts,
            total_memories,
            independence_threshold,
        ),
    )
    return _orient_edges(skeleton, co_occurrences, entity_first_seen or {})


def _build_directed_adjacency(edges: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Build adjacency list from directed edges only."""
    adj: dict[str, list[str]] = {}
    for edge in edges:
        if edge.get("is_directed"):
            adj.setdefault(edge["source"], []).append(edge["target"])
    return adj


def find_causal_chain(
    edges: list[dict[str, Any]],
    start: str,
    max_depth: int = 5,
) -> list[list[str]]:
    """Find causal chains starting from a given entity.

    Returns list of paths: [[start, step1, step2, ...], ...].
    """
    adj = _build_directed_adjacency(edges)

    if start not in adj:
        return []

    paths: list[list[str]] = []
    stack: list[tuple[str, list[str]]] = [(start, [start])]

    while stack:
        node, path = stack.pop()
        if len(path) > max_depth:
            continue

        neighbors = adj.get(node, [])
        if not neighbors and len(path) > 1:
            paths.append(path)
            continue

        extended = False
        for neighbor in neighbors:
            if neighbor not in path:  # Avoid cycles
                stack.append((neighbor, path + [neighbor]))
                extended = True

        if not extended and len(path) > 1:
            paths.append(path)

    return paths


def find_common_causes(
    edges: list[dict[str, Any]],
    entity_a: str,
    entity_b: str,
) -> list[str]:
    """Find common causes of two entities (fork structures)."""
    # Build reverse adjacency (target → sources)
    reverse_adj: dict[str, set[str]] = {}
    for edge in edges:
        if edge.get("is_directed"):
            reverse_adj.setdefault(edge["target"], set()).add(edge["source"])

    causes_a = reverse_adj.get(entity_a, set())
    causes_b = reverse_adj.get(entity_b, set())

    return sorted(causes_a & causes_b)
