"""Fractal memory tree — multi-scale hierarchical retrieval.

Implements a 3-level memory hierarchy:
  - Level 0: Individual memories (leaf nodes)
  - Level 1: Similarity-based clusters (agglomerative)
  - Level 2: Directory/domain-level root clusters

Adaptive retrieval weights query length against hierarchy levels:
  - Short queries -> broad Level 2 results
  - Long queries -> specific Level 0 results

Pure business logic — no I/O. Receives pre-computed data, returns hierarchy.
"""

from __future__ import annotations

from typing import Any, Callable

from mcp_server.core.fractal_clustering import (
    UnionFind,
    agglomerative_cluster,
    build_l1_clusters,
    build_l2_clusters,
    compute_centroid,
)


__all__ = [
    "UnionFind",
    "agglomerative_cluster",
    "compute_centroid",
    "build_hierarchy",
    "compute_level_weights",
    "score_against_hierarchy",
    "drill_down",
    "roll_up",
]


# ── Hierarchy Construction ────────────────────────────────────────────────


def build_hierarchy(
    memories: list[dict[str, Any]],
    similarity_fn: Callable,
    embedding_dim: int,
    l1_threshold: float = 0.6,
) -> dict[str, Any]:
    """Build a 3-level fractal memory tree.

    Returns:
      - levels: {0: [memories], 1: [clusters], 2: [root_clusters]}
      - cluster_map: {cluster_id: cluster_data}
      - stats: {total_memories, l1_clusters, l2_clusters}
    """
    if not memories:
        return {
            "levels": {0: [], 1: [], 2: []},
            "cluster_map": {},
            "stats": {"total_memories": 0, "l1_clusters": 0, "l2_clusters": 0},
        }

    l1_raw = agglomerative_cluster(memories, similarity_fn, threshold=l1_threshold)
    level_1, cluster_map = build_l1_clusters(l1_raw, embedding_dim)
    level_2, l2_map = build_l2_clusters(level_1, memories, embedding_dim)
    cluster_map.update(l2_map)

    return {
        "levels": {0: memories, 1: level_1, 2: level_2},
        "cluster_map": cluster_map,
        "stats": {
            "total_memories": len(memories),
            "l1_clusters": len(level_1),
            "l2_clusters": len(level_2),
        },
    }


# ── Adaptive Retrieval Weighting ──────────────────────────────────────────


def compute_level_weights(query: str) -> tuple[float, float, float]:
    """Compute retrieval weights for each hierarchy level based on query length.

    Returns (level_0_weight, level_1_weight, level_2_weight).

    Short queries (<10 words) -> broad (L2 heavy)
    Long queries (>30 words) -> specific (L0 heavy)
    Medium -> balanced
    """
    word_count = len(query.split())

    if word_count < 10:
        return 0.3, 0.5, 1.0
    elif word_count > 30:
        return 1.0, 0.5, 0.3
    else:
        return 0.7, 0.7, 0.7


# ── Scoring ──────────────────────────────────────────────────────────────


def score_against_hierarchy(
    query_embedding: bytes,
    hierarchy: dict[str, Any],
    similarity_fn: Callable,
    query: str = "",
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """Score memories against the fractal hierarchy with adaptive weighting.

    Returns scored results with hierarchy context.
    """
    w0, w1, w2 = compute_level_weights(query)
    results: dict[int, dict] = {}

    _score_level_0(hierarchy, query_embedding, similarity_fn, w0, results)
    _score_level_1(hierarchy, query_embedding, similarity_fn, w1, results)
    _score_level_2(hierarchy, query_embedding, similarity_fn, w2, results)

    sorted_results = sorted(results.values(), key=lambda r: r["score"], reverse=True)
    return sorted_results[:max_results]


def _score_level_0(
    hierarchy: dict[str, Any],
    query_embedding: bytes,
    similarity_fn: Callable,
    weight: float,
    results: dict[int, dict],
) -> None:
    """Score individual memories at Level 0."""
    for mem in hierarchy["levels"].get(0, []):
        emb = mem.get("embedding")
        if emb is None:
            continue
        sim = similarity_fn(query_embedding, emb)
        mid = mem.get("id")
        if mid is not None:
            results[mid] = {
                "memory_id": mid,
                "score": sim * weight,
                "level_scores": {"L0": sim},
                "matched_level": 0,
            }


def _score_level_1(
    hierarchy: dict[str, Any],
    query_embedding: bytes,
    similarity_fn: Callable,
    weight: float,
    results: dict[int, dict],
) -> None:
    """Distribute cluster-level scores to member memories at Level 1."""
    for cluster in hierarchy["levels"].get(1, []):
        centroid = cluster.get("centroid")
        if centroid is None:
            continue
        sim = similarity_fn(query_embedding, centroid)
        for mid in cluster.get("memory_ids", []):
            if mid in results:
                results[mid]["score"] += sim * weight
                results[mid]["level_scores"]["L1"] = sim
            else:
                results[mid] = {
                    "memory_id": mid,
                    "score": sim * weight,
                    "level_scores": {"L1": sim},
                    "matched_level": 1,
                }


def _score_level_2(
    hierarchy: dict[str, Any],
    query_embedding: bytes,
    similarity_fn: Callable,
    weight: float,
    results: dict[int, dict],
) -> None:
    """Distribute root-cluster scores to member memories at Level 2."""
    for root in hierarchy["levels"].get(2, []):
        centroid = root.get("centroid")
        if centroid is None:
            continue
        sim = similarity_fn(query_embedding, centroid)
        for child_id in root.get("child_clusters", []):
            child = hierarchy["cluster_map"].get(child_id)
            if not child:
                continue
            for mid in child.get("memory_ids", []):
                if mid in results:
                    results[mid]["score"] += sim * weight
                    results[mid]["level_scores"]["L2"] = sim
                else:
                    results[mid] = {
                        "memory_id": mid,
                        "score": sim * weight,
                        "level_scores": {"L2": sim},
                        "matched_level": 2,
                    }


# ── Navigation ────────────────────────────────────────────────────────────


def drill_down(
    cluster_id: str,
    hierarchy: dict[str, Any],
) -> list[dict[str, Any]]:
    """Navigate from a cluster to its children/memories.

    For L2 cluster -> returns L1 child clusters.
    For L1 cluster -> returns memory IDs.
    """
    cluster = hierarchy["cluster_map"].get(cluster_id)
    if not cluster:
        return []

    if cluster["level"] == 2:
        children = []
        for child_id in cluster.get("child_clusters", []):
            child = hierarchy["cluster_map"].get(child_id)
            if child:
                children.append(child)
        return children

    elif cluster["level"] == 1:
        return [{"memory_id": mid} for mid in cluster.get("memory_ids", [])]

    return []


def roll_up(
    memory_id: int,
    hierarchy: dict[str, Any],
) -> list[str]:
    """Given a memory ID, return its cluster hierarchy path.

    Returns [L1_cluster_id, L2_cluster_id] or partial path.
    """
    path: list[str] = []

    for cluster in hierarchy["levels"].get(1, []):
        if memory_id in cluster.get("memory_ids", []):
            path.append(cluster["cluster_id"])
            for root in hierarchy["levels"].get(2, []):
                if cluster["cluster_id"] in root.get("child_clusters", []):
                    path.append(root["cluster_id"])
                    break
            break

    return path
