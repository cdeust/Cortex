"""Cognitive map — Successor Representation for navigation-based memory retrieval.

Tracks temporal co-access (memories accessed within a session window are linked)
and uses discounted SR weights for retrieval scoring and BFS navigation.

Pure business logic — no I/O. Callers pass pre-fetched access history.

References:
  Dayan (1993) "Improving Generalization for Temporal Difference Learning"
  Stachenfeld et al. (2017) "The Hippocampus as a Predictive Map"
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

# ── SR parameters ─────────────────────────────────────────────────────────

# Temporal decay for SR update: discount for co-access distance
_SR_DISCOUNT = 0.9

# Session window: memories accessed within this many hours are co-access candidates
_CO_ACCESS_WINDOW_HOURS = 2.0

# Maximum BFS depth for navigate_memory tool
_MAX_NAVIGATE_DEPTH = 3


# ── Co-access graph building ──────────────────────────────────────────────


def build_co_access_graph(
    access_sequences: list[list[int]],
    discount: float = _SR_DISCOUNT,
) -> dict[int, dict[int, float]]:
    """Build a weighted co-access graph from access sequences.

    For each sequence [m1, m2, m3, ...], the SR update gives:
      SR[m1][m2] += 1
      SR[m1][m3] += discount
      SR[m1][m4] += discount^2  ...

    This implements a forward-looking reachability score from any start node.

    Args:
        access_sequences: List of ordered memory ID sequences from sessions.
        discount: Temporal discount factor γ (0 < γ < 1).

    Returns:
        Nested dict: sr_graph[source_id][target_id] = cumulative SR weight.
    """
    sr_graph: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))

    for seq in access_sequences:
        for i, src in enumerate(seq):
            for j in range(i + 1, len(seq)):
                tgt = seq[j]
                dist = j - i
                weight = discount ** (dist - 1)
                sr_graph[src][tgt] += weight
                # Bidirectional (memory access is often symmetric)
                sr_graph[tgt][src] += weight * discount  # back-link weighted less

    return sr_graph


def _parse_iso_timestamp(s: str) -> float:
    """Parse ISO timestamp to Unix float, return 0 on error."""
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0


def _link_nearby_memories(
    mems_sorted: list[dict[str, Any]],
    window_secs: float,
    graph: dict[int, dict[int, float]],
) -> None:
    """Link memories within the time window, updating graph in-place."""
    for i, mem_a in enumerate(mems_sorted):
        t_a = _parse_iso_timestamp(mem_a["last_accessed"])
        mid_a = mem_a["id"]

        for j in range(i + 1, len(mems_sorted)):
            mem_b = mems_sorted[j]
            t_b = _parse_iso_timestamp(mem_b["last_accessed"])
            gap = abs(t_b - t_a)

            if gap > window_secs:
                break  # Sorted, so all further pairs are further apart

            mid_b = mem_b["id"]
            proximity = 1.0 - (gap / window_secs)
            graph[mid_a][mid_b] = proximity
            graph[mid_b][mid_a] = proximity


def build_temporal_co_access(
    memories_with_access_time: list[dict[str, Any]],
    window_hours: float = _CO_ACCESS_WINDOW_HOURS,
) -> dict[int, dict[int, float]]:
    """Build co-access graph from memories' last_accessed timestamps.

    Two memories are considered co-accessed if their last_accessed times
    are within window_hours of each other.
    """
    mems_sorted = sorted(
        [m for m in memories_with_access_time if m.get("last_accessed")],
        key=lambda m: _parse_iso_timestamp(m["last_accessed"]),
    )

    graph: dict[int, dict[int, float]] = defaultdict(dict)
    _link_nearby_memories(mems_sorted, window_hours * 3600.0, graph)
    return graph


# ── SR retrieval scoring ──────────────────────────────────────────────────


def compute_sr_scores(
    seed_memory_ids: list[int],
    sr_graph: dict[int, dict[int, float]],
    top_k: int = 20,
) -> list[tuple[int, float]]:
    """Score candidate memories by SR affinity to seed memories.

    SR score for candidate c = sum of SR[seed][c] for all seeds.
    Seeds themselves are excluded from results.

    Args:
        seed_memory_ids: Recently recalled/accessed memory IDs (seeds).
        sr_graph: Co-access graph from build_co_access_graph or build_temporal_co_access.
        top_k: Maximum results.

    Returns:
        List of (memory_id, sr_score) sorted descending.
    """
    if not seed_memory_ids or not sr_graph:
        return []

    seed_set = set(seed_memory_ids)
    scores: dict[int, float] = defaultdict(float)

    for seed_id in seed_memory_ids:
        neighbors = sr_graph.get(seed_id, {})
        for cand_id, weight in neighbors.items():
            if cand_id not in seed_set:
                scores[cand_id] += weight

    # Normalize by number of seeds for consistency
    n_seeds = len(seed_memory_ids)
    normalized = {mid: score / n_seeds for mid, score in scores.items()}

    result = sorted(normalized.items(), key=lambda x: x[1], reverse=True)
    return result[:top_k]


# ── Navigation ────────────────────────────────────────────────────────────


def _enqueue_neighbors(
    current_id: int,
    cumulative_weight: float,
    depth: int,
    path: list[int],
    sr_graph: dict[int, dict[int, float]],
    visited: dict[int, dict[str, Any]],
    queue: list[tuple[int, float, int, list[int]]],
    min_weight: float,
) -> None:
    """Enqueue unvisited neighbors above min_weight into the BFS queue."""
    neighbors = sr_graph.get(current_id, {})
    for neighbor_id, weight in sorted(
        neighbors.items(), key=lambda x: x[1], reverse=True
    ):
        if neighbor_id not in visited and weight >= min_weight:
            new_weight = cumulative_weight * weight
            queue.append((neighbor_id, new_weight, depth + 1, path + [neighbor_id]))


def navigate_from(
    start_memory_id: int,
    sr_graph: dict[int, dict[int, float]],
    max_depth: int = _MAX_NAVIGATE_DEPTH,
    min_weight: float = 0.05,
) -> dict[int, dict[str, Any]]:
    """BFS navigation through SR graph from a starting memory.

    Returns all reachable nodes within max_depth steps, with their
    cumulative SR distance and hop count.
    """
    visited: dict[int, dict[str, Any]] = {}
    queue: list[tuple[int, float, int, list[int]]] = [
        (start_memory_id, 1.0, 0, [start_memory_id])
    ]

    while queue:
        current_id, cumulative_weight, depth, path = queue.pop(0)

        if current_id in visited:
            continue
        if depth > 0:
            visited[current_id] = {
                "distance": round(1.0 - cumulative_weight, 4),
                "hops": depth,
                "path": path,
            }

        if depth < max_depth:
            _enqueue_neighbors(
                current_id,
                cumulative_weight,
                depth,
                path,
                sr_graph,
                visited,
                queue,
                min_weight,
            )

    return visited


# ── 2D projection (for visualization) ────────────────────────────────────


def _spring_relax(
    positions: list[list[float]],
    sr_graph: dict[int, dict[int, float]],
    idx_map: dict[int, int],
    iterations: int = 5,
) -> None:
    """Apply force-directed spring relaxation to positions in-place."""
    n = len(positions)
    for _ in range(iterations):
        forces = [[0.0, 0.0] for _ in range(n)]
        for mid, neighbors in sr_graph.items():
            if mid not in idx_map:
                continue
            i = idx_map[mid]
            for neighbor_id, weight in neighbors.items():
                if neighbor_id not in idx_map:
                    continue
                j = idx_map[neighbor_id]
                dx = positions[j][0] - positions[i][0]
                dy = positions[j][1] - positions[i][1]
                forces[i][0] += dx * weight * 0.1
                forces[i][1] += dy * weight * 0.1

        for i in range(n):
            positions[i][0] += forces[i][0]
            positions[i][1] += forces[i][1]


def project_to_2d(
    sr_graph: dict[int, dict[int, float]],
    memory_ids: list[int],
) -> dict[int, tuple[float, float]]:
    """Project memories to 2D coordinates using spectral embedding of the SR graph.

    Uses a simple force-directed approximation:
    - Strongly connected memories cluster near each other
    - Isolated memories spread outward

    Args:
        sr_graph: Co-access graph.
        memory_ids: All memory IDs to project.

    Returns:
        Dict of {memory_id: (x, y)} coordinates in [-1, 1].
    """
    if not memory_ids:
        return {}

    n = len(memory_ids)
    idx_map = {mid: i for i, mid in enumerate(memory_ids)}
    positions = [
        [math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n)] for i in range(n)
    ]

    _spring_relax(positions, sr_graph, idx_map)

    all_coords = [v for p in positions for v in p]
    max_abs = max(max(abs(v) for v in all_coords), 1e-9)

    return {
        mid: (
            round(positions[idx_map[mid]][0] / max_abs, 4),
            round(positions[idx_map[mid]][1] / max_abs, 4),
        )
        for mid in memory_ids
    }
