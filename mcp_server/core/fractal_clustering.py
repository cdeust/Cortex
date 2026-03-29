"""Fractal clustering primitives — Union-Find, agglomerative clustering, centroids.

Extracted from fractal.py to keep each module under 300 lines.
Used by fractal.py for hierarchy construction.

Pure business logic — no I/O.
"""

from __future__ import annotations

import struct
from typing import Any, Callable

# ── Union-Find for Clustering ─────────────────────────────────────────────


class UnionFind:
    """Disjoint-set data structure with path compression and union by rank."""

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1


# ── Clustering ────────────────────────────────────────────────────────────


def _merge_similar_pairs(
    memories: list[dict[str, Any]],
    uf: UnionFind,
    similarity_fn: Callable,
    threshold: float,
) -> None:
    """Union all pairs whose embeddings exceed the similarity threshold."""
    n = len(memories)
    for i in range(n):
        emb_i = memories[i].get("embedding")
        if emb_i is None:
            continue
        for j in range(i + 1, n):
            emb_j = memories[j].get("embedding")
            if emb_j is None:
                continue
            if similarity_fn(emb_i, emb_j) >= threshold:
                uf.union(i, j)


def agglomerative_cluster(
    memories: list[dict[str, Any]],
    similarity_fn: Callable,
    threshold: float = 0.6,
) -> list[list[dict[str, Any]]]:
    """Single-linkage agglomerative clustering via Union-Find.

    Parameters
    ----------
    memories:
        Each dict must have an "embedding" field.
    similarity_fn:
        Callable(emb_a, emb_b) -> float in [0, 1].
    threshold:
        Minimum similarity for merging.
    """
    n = len(memories)
    if n == 0:
        return []
    if n == 1:
        return [memories]

    uf = UnionFind(n)
    _merge_similar_pairs(memories, uf, similarity_fn, threshold)

    groups: dict[int, list[dict]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(memories[i])
    return list(groups.values())


# ── Centroid Computation ──────────────────────────────────────────────────


def compute_centroid(
    embeddings: list[bytes],
    dim: int,
) -> bytes | None:
    """Compute mean centroid of byte-encoded float32 embeddings.

    Returns centroid as bytes, or None if no valid embeddings.
    """
    valid: list[list[float]] = []
    for emb in embeddings:
        if emb is None or len(emb) < dim * 4:
            continue
        values = struct.unpack(f"{dim}f", emb[: dim * 4])
        valid.append(list(values))

    if not valid:
        return None

    n = len(valid)
    centroid = [sum(v[d] for v in valid) / n for d in range(dim)]

    magnitude = sum(c * c for c in centroid) ** 0.5
    if magnitude > 0:
        centroid = [c / magnitude for c in centroid]

    return struct.pack(f"{dim}f", *centroid)


# ── Hierarchy Building Helpers ────────────────────────────────────────────


def build_l1_clusters(
    l1_raw: list[list[dict[str, Any]]],
    embedding_dim: int,
) -> tuple[list[dict], dict[str, dict]]:
    """Build Level 1 cluster data from raw agglomerative groups.

    Returns (level_1_list, cluster_map_entries).
    """
    level_1: list[dict] = []
    cluster_map: dict[str, dict] = {}

    for i, cluster in enumerate(l1_raw):
        cluster_id = f"L1-{i}"
        embeddings = [m.get("embedding") for m in cluster]
        centroid = compute_centroid(embeddings, embedding_dim)

        cluster_data = {
            "cluster_id": cluster_id,
            "level": 1,
            "memory_ids": [m.get("id") for m in cluster if m.get("id") is not None],
            "centroid": centroid,
            "size": len(cluster),
            "avg_heat": (
                sum(m.get("heat", 0.5) for m in cluster) / len(cluster)
                if cluster
                else 0
            ),
        }
        level_1.append(cluster_data)
        cluster_map[cluster_id] = cluster_data

    return level_1, cluster_map


def build_l2_clusters(
    level_1: list[dict],
    memories: list[dict[str, Any]],
    embedding_dim: int,
) -> tuple[list[dict], dict[str, dict]]:
    """Build Level 2 root clusters by grouping L1 clusters by directory/domain.

    Returns (level_2_list, cluster_map_entries).
    """
    dir_groups: dict[str, list[dict]] = {}
    for cluster_data in level_1:
        dominant_dir = _find_dominant_directory(cluster_data, memories)
        dir_groups.setdefault(dominant_dir, []).append(cluster_data)

    level_2: list[dict] = []
    cluster_map: dict[str, dict] = {}

    for j, (dir_key, l1_group) in enumerate(dir_groups.items()):
        cluster_id = f"L2-{j}"
        l1_centroids = [c["centroid"] for c in l1_group if c.get("centroid")]
        centroid = (
            compute_centroid(l1_centroids, embedding_dim) if l1_centroids else None
        )

        cluster_data = {
            "cluster_id": cluster_id,
            "level": 2,
            "directory": dir_key,
            "child_clusters": [c["cluster_id"] for c in l1_group],
            "total_memories": sum(c["size"] for c in l1_group),
            "centroid": centroid,
        }
        level_2.append(cluster_data)
        cluster_map[cluster_id] = cluster_data

    return level_2, cluster_map


def _find_dominant_directory(
    cluster_data: dict,
    memories: list[dict[str, Any]],
) -> str:
    """Find the most common directory/domain among a cluster's member memories."""
    dirs: dict[str, int] = {}
    for mid in cluster_data["memory_ids"]:
        mem = next((m for m in memories if m.get("id") == mid), None)
        if mem:
            d = mem.get("directory_context") or mem.get("domain") or "global"
            dirs[d] = dirs.get(d, 0) + 1

    return max(dirs, key=dirs.get) if dirs else "global"
