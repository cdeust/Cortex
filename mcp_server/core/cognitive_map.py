"""Cognitive map — Successor Representation for navigation-based memory retrieval.

Tracks temporal co-access (memories accessed within a session window are linked)
and uses discounted SR weights for retrieval scoring and BFS navigation.

Pure business logic — no I/O. Callers pass pre-fetched access history.

References:
  Dayan (1993) "Improving Generalization for Temporal Difference Learning"
    — the Successor Representation M = (I - γT)⁻¹.
  Stachenfeld et al. (2017) "The Hippocampus as a Predictive Map" — the SR
    matrix's eigenvectors form a low-dimensional embedding of the state
    graph (grid-cell-like); used by ``project_to_2d``.
  Belkin & Niyogi (2003) "Laplacian Eigenmaps" — those eigenvectors are
    computed here via S = D^(-1/2) W D^(-1/2), which is similar to T = D⁻¹W.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np

# ── SR parameters ─────────────────────────────────────────────────────────

# The 2D spectral embedding (project_to_2d) uses the eigenvectors of the SR
# matrix M = (I - γT)⁻¹, which are a function of T alone — they are identical
# for every discount γ ∈ (0, 1) — so no γ value is needed here.

# Session window: memories accessed within this many hours are co-access candidates
_CO_ACCESS_WINDOW_HOURS = 2.0

# Maximum BFS depth for navigate_memory tool
_MAX_NAVIGATE_DEPTH = 3


# ── Co-access graph building ──────────────────────────────────────────────


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
        sr_graph: Co-access graph from build_temporal_co_access.
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


# ── 2D projection: SR spectral embedding ─────────────────────────────────


def _symmetric_normalized_adjacency(
    sr_graph: dict[int, dict[int, float]],
    active_ids: list[int],
) -> np.ndarray:
    """Build S = D^(-1/2) W D^(-1/2) over ``active_ids`` (all degree > 0).

    W is the symmetrised co-access weight matrix. S is similar to the random
    walk T = D⁻¹W, hence shares the eigenvectors of the SR matrix
    M = (I - γT)⁻¹ — so its spectrum yields the SR/Laplacian eigenmap
    (Stachenfeld 2017; Belkin & Niyogi 2003).
    """
    n = len(active_ids)
    idx = {mid: i for i, mid in enumerate(active_ids)}
    w = np.zeros((n, n), dtype=np.float64)
    for src, neighbors in sr_graph.items():
        if src not in idx:
            continue
        for tgt, weight in neighbors.items():
            if tgt in idx:
                w[idx[src], idx[tgt]] = weight
    w = 0.5 * (w + w.T)  # symmetrise (co-access affinity is undirected)

    inv_sqrt = 1.0 / np.sqrt(w.sum(axis=1))  # active nodes ⇒ degree > 0
    return inv_sqrt[:, None] * w * inv_sqrt[None, :]


def _active_node_degrees(
    sr_graph: dict[int, dict[int, float]],
    memory_ids: list[int],
) -> set[int]:
    """IDs in ``memory_ids`` that carry at least one (in- or out-) edge."""
    present = set(memory_ids)
    active: set[int] = set()
    for src, neighbors in sr_graph.items():
        for tgt, weight in neighbors.items():
            if weight == 0.0:
                continue
            if src in present:
                active.add(src)
            if tgt in present:
                active.add(tgt)
    return active


def project_to_2d(
    sr_graph: dict[int, dict[int, float]],
    memory_ids: list[int],
) -> dict[int, tuple[float, float]]:
    """Project memories to 2D via the SR spectral embedding.

    Faithful to Stachenfeld et al. (2017): the SR eigenvectors embed the
    state graph. They are computed from S = D^(-1/2) W D^(-1/2) (similar to
    T = D⁻¹W, so sharing the SR matrix's eigenvectors — Belkin & Niyogi
    2003). S's top eigenvalue is the trivial stationary component
    (eigenvector ∝ √degree); the two subdominant eigenvectors are the
    grid-cell-like (x, y) axes, placing co-accessed memories near each other.
    Isolated memories (no edge) have no predictive map → placed at origin.

    Args:
        sr_graph: Symmetric co-access graph from build_temporal_co_access.
        memory_ids: All memory IDs to project.

    Returns:
        Dict of {memory_id: (x, y)} coordinates scaled into [-1, 1].
    """
    if not memory_ids:
        return {}

    active = _active_node_degrees(sr_graph, memory_ids)
    coords: dict[int, tuple[float, float]] = {
        mid: (0.0, 0.0) for mid in memory_ids if mid not in active
    }
    active_ids = [mid for mid in memory_ids if mid in active]
    if len(active_ids) < 2:
        # 0 or 1 connected node: no non-trivial axis to embed along.
        coords.update({mid: (0.0, 0.0) for mid in active_ids})
        return coords

    s = _symmetric_normalized_adjacency(sr_graph, active_ids)
    # eigh: ascending eigenvalues, orthonormal eigenvectors (S is symmetric).
    eigvals, eigvecs = np.linalg.eigh(s)
    order = np.argsort(eigvals)[::-1]  # descending: index 0 is the trivial top
    # Subdominant eigenvectors as the two embedding axes (skip the stationary).
    x_axis = eigvecs[:, order[1]]
    y_axis = eigvecs[:, order[2]] if len(active_ids) >= 3 else np.zeros(len(active_ids))

    xy = np.column_stack((x_axis, y_axis))
    max_abs = max(float(np.abs(xy).max()), 1e-9)
    xy = xy / max_abs

    for i, mid in enumerate(active_ids):
        coords[mid] = (round(float(xy[i, 0]), 4), round(float(xy[i, 1]), 4))
    return coords
