"""Tests for mcp_server.core.fractal — hierarchical memory tree."""

import struct

from mcp_server.core.fractal import (
    UnionFind,
    agglomerative_cluster,
    compute_centroid,
    build_hierarchy,
    compute_level_weights,
    score_against_hierarchy,
    drill_down,
    roll_up,
)

DIM = 4


def _make_emb(*values):
    """Create a bytes embedding from float values."""
    padded = list(values) + [0.0] * (DIM - len(values))
    return struct.pack(f"{DIM}f", *padded[:DIM])


def _exact_sim(a, b):
    """Exact match similarity."""
    if a is None or b is None:
        return 0.0
    return 1.0 if a == b else 0.0


def _cosine_sim(a, b):
    """Simple cosine similarity for bytes embeddings."""
    if a is None or b is None:
        return 0.0
    va = struct.unpack(f"{DIM}f", a[: DIM * 4])
    vb = struct.unpack(f"{DIM}f", b[: DIM * 4])
    dot = sum(x * y for x, y in zip(va, vb))
    na = sum(x * x for x in va) ** 0.5
    nb = sum(x * x for x in vb) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class TestUnionFind:
    def test_basic_union(self):
        uf = UnionFind(5)
        uf.union(0, 1)
        uf.union(1, 2)
        assert uf.find(0) == uf.find(2)
        assert uf.find(0) != uf.find(3)

    def test_path_compression(self):
        uf = UnionFind(10)
        for i in range(9):
            uf.union(i, i + 1)
        root = uf.find(0)
        assert uf.find(9) == root

    def test_single_element(self):
        uf = UnionFind(1)
        assert uf.find(0) == 0


class TestAgglomerativeCluster:
    def test_identical_embeddings_cluster(self):
        mems = [
            {"id": 1, "embedding": _make_emb(1, 0, 0, 0)},
            {"id": 2, "embedding": _make_emb(1, 0, 0, 0)},
            {"id": 3, "embedding": _make_emb(0, 1, 0, 0)},
        ]
        clusters = agglomerative_cluster(mems, _cosine_sim, threshold=0.9)
        assert len(clusters) == 2

    def test_all_different(self):
        mems = [
            {"id": 1, "embedding": _make_emb(1, 0, 0, 0)},
            {"id": 2, "embedding": _make_emb(0, 1, 0, 0)},
            {"id": 3, "embedding": _make_emb(0, 0, 1, 0)},
        ]
        clusters = agglomerative_cluster(mems, _cosine_sim, threshold=0.9)
        assert len(clusters) == 3

    def test_empty_input(self):
        assert agglomerative_cluster([], _cosine_sim) == []

    def test_single_memory(self):
        mems = [{"id": 1, "embedding": _make_emb(1, 0, 0, 0)}]
        clusters = agglomerative_cluster(mems, _cosine_sim)
        assert len(clusters) == 1

    def test_missing_embeddings(self):
        mems = [{"id": 1}, {"id": 2, "embedding": _make_emb(1, 0, 0, 0)}]
        clusters = agglomerative_cluster(mems, _cosine_sim)
        assert len(clusters) == 2  # Each its own cluster


class TestComputeCentroid:
    def test_single_embedding(self):
        emb = _make_emb(1, 0, 0, 0)
        centroid = compute_centroid([emb], DIM)
        assert centroid is not None
        values = struct.unpack(f"{DIM}f", centroid)
        assert abs(values[0] - 1.0) < 0.01

    def test_two_embeddings(self):
        emb1 = _make_emb(1, 0, 0, 0)
        emb2 = _make_emb(0, 1, 0, 0)
        centroid = compute_centroid([emb1, emb2], DIM)
        assert centroid is not None
        values = struct.unpack(f"{DIM}f", centroid)
        # Mean of [1,0,0,0] and [0,1,0,0] = [0.5,0.5,0,0], normalized
        assert abs(values[0] - values[1]) < 0.01

    def test_no_valid_embeddings(self):
        assert compute_centroid([None], DIM) is None
        assert compute_centroid([], DIM) is None


class TestBuildHierarchy:
    def test_basic_hierarchy(self):
        mems = [
            {
                "id": 1,
                "embedding": _make_emb(1, 0, 0, 0),
                "domain": "backend",
                "heat": 0.8,
            },
            {
                "id": 2,
                "embedding": _make_emb(1, 0.1, 0, 0),
                "domain": "backend",
                "heat": 0.7,
            },
            {
                "id": 3,
                "embedding": _make_emb(0, 1, 0, 0),
                "domain": "frontend",
                "heat": 0.5,
            },
        ]
        h = build_hierarchy(mems, _cosine_sim, DIM, l1_threshold=0.9)
        assert h["stats"]["total_memories"] == 3
        assert h["stats"]["l1_clusters"] >= 1
        assert h["stats"]["l2_clusters"] >= 1
        assert len(h["levels"][0]) == 3
        assert len(h["levels"][1]) >= 1

    def test_empty_input(self):
        h = build_hierarchy([], _exact_sim, DIM)
        assert h["stats"]["total_memories"] == 0

    def test_single_memory(self):
        mems = [
            {"id": 1, "embedding": _make_emb(1, 0, 0, 0), "domain": "test", "heat": 0.5}
        ]
        h = build_hierarchy(mems, _exact_sim, DIM)
        assert h["stats"]["total_memories"] == 1
        assert h["stats"]["l1_clusters"] == 1


class TestComputeLevelWeights:
    def test_short_query_broad(self):
        w0, w1, w2 = compute_level_weights("find memories")
        assert w2 > w0  # L2 favored

    def test_long_query_specific(self):
        long_q = " ".join(["word"] * 35)
        w0, w1, w2 = compute_level_weights(long_q)
        assert w0 > w2  # L0 favored

    def test_medium_query_balanced(self):
        mid_q = " ".join(["word"] * 15)
        w0, w1, w2 = compute_level_weights(mid_q)
        assert w0 == w1 == w2


class TestScoreAgainstHierarchy:
    def test_scoring(self):
        mems = [
            {
                "id": 1,
                "embedding": _make_emb(1, 0, 0, 0),
                "domain": "test",
                "heat": 0.8,
            },
            {
                "id": 2,
                "embedding": _make_emb(0, 1, 0, 0),
                "domain": "test",
                "heat": 0.5,
            },
        ]
        h = build_hierarchy(mems, _cosine_sim, DIM)
        query_emb = _make_emb(1, 0, 0, 0)
        results = score_against_hierarchy(query_emb, h, _cosine_sim, "test query")
        assert len(results) > 0
        # Memory 1 should score higher (closer to query)
        assert results[0]["memory_id"] == 1

    def test_empty_hierarchy(self):
        h = build_hierarchy([], _exact_sim, DIM)
        results = score_against_hierarchy(_make_emb(1, 0, 0, 0), h, _exact_sim)
        assert results == []


class TestDrillDown:
    def test_drill_l2(self):
        mems = [
            {"id": 1, "embedding": _make_emb(1, 0, 0, 0), "domain": "a", "heat": 0.5},
            {"id": 2, "embedding": _make_emb(0, 1, 0, 0), "domain": "b", "heat": 0.5},
        ]
        h = build_hierarchy(mems, _cosine_sim, DIM)
        l2_clusters = h["levels"][2]
        if l2_clusters:
            children = drill_down(l2_clusters[0]["cluster_id"], h)
            assert len(children) >= 1

    def test_drill_l1(self):
        mems = [
            {"id": 1, "embedding": _make_emb(1, 0, 0, 0), "domain": "a", "heat": 0.5},
        ]
        h = build_hierarchy(mems, _cosine_sim, DIM)
        l1_clusters = h["levels"][1]
        if l1_clusters:
            children = drill_down(l1_clusters[0]["cluster_id"], h)
            assert len(children) >= 1

    def test_invalid_cluster(self):
        h = build_hierarchy([], _exact_sim, DIM)
        assert drill_down("nonexistent", h) == []


class TestRollUp:
    def test_roll_up_path(self):
        mems = [
            {"id": 1, "embedding": _make_emb(1, 0, 0, 0), "domain": "a", "heat": 0.5},
        ]
        h = build_hierarchy(mems, _cosine_sim, DIM)
        path = roll_up(1, h)
        assert len(path) >= 1  # At least L1 cluster

    def test_unknown_memory(self):
        h = build_hierarchy([], _exact_sim, DIM)
        path = roll_up(999, h)
        assert path == []
