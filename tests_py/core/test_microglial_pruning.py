"""Tests for mcp_server.core.microglial_pruning — disparity filter pruning.

Tests the Serrano et al. (2009) disparity filter for edge pruning and
standard orphan detection for entity cleanup.
"""

import math

from mcp_server.core.microglial_pruning import (
    _build_adjacency,
    _disparity_alpha,
    _temporal_decay,
    compute_pruning_stats,
    identify_orphaned_entities,
    identify_prunable_edges,
)


def _edge(src, tgt, weight=0.5, hours=0):
    return {
        "source_entity_id": src,
        "target_entity_id": tgt,
        "weight": weight,
        "hours_since_co_access": hours,
    }


def _entity(id, heat=0.5, access_count=3, is_protected=False):
    return {
        "id": id,
        "heat": heat,
        "access_count": access_count,
        "is_protected": is_protected,
    }


class TestTemporalDecay:
    def test_zero_hours_returns_one(self):
        assert _temporal_decay(0, 168.0) == 1.0

    def test_one_half_life_returns_half(self):
        result = _temporal_decay(168.0, 168.0)
        assert abs(result - 0.5) < 1e-9

    def test_two_half_lives_returns_quarter(self):
        result = _temporal_decay(336.0, 168.0)
        assert abs(result - 0.25) < 1e-9

    def test_negative_hours_returns_one(self):
        assert _temporal_decay(-10, 168.0) == 1.0


class TestDisparityAlpha:
    def test_degree_one_always_significant(self):
        # k=1 => alpha=0, always significant
        assert _disparity_alpha(0.5, 1) == 0.0

    def test_uniform_two_edges(self):
        # k=2, p=0.5 => alpha = (1-0.5)^1 = 0.5
        assert _disparity_alpha(0.5, 2) == 0.5

    def test_dominant_edge(self):
        # k=3, p=0.9 => alpha = (0.1)^2 = 0.01 (significant)
        result = _disparity_alpha(0.9, 3)
        assert abs(result - 0.01) < 1e-9

    def test_weak_edge_high_degree(self):
        # k=5, p=0.1 => alpha = (0.9)^4 = 0.6561 (not significant)
        result = _disparity_alpha(0.1, 5)
        assert abs(result - 0.6561) < 1e-4


class TestBuildAdjacency:
    def test_symmetric_adjacency(self):
        edges = [_edge(1, 2, weight=1.0, hours=0)]
        adj, strength, degree = _build_adjacency(edges, 168.0)
        assert adj[1][2] == 1.0
        assert adj[2][1] == 1.0
        assert strength[1] == 1.0
        assert degree[1] == 1

    def test_temporal_decay_applied(self):
        edges = [_edge(1, 2, weight=1.0, hours=168)]
        adj, strength, degree = _build_adjacency(edges, 168.0)
        assert abs(adj[1][2] - 0.5) < 1e-9

    def test_multi_edge_strength(self):
        edges = [
            _edge(1, 2, weight=1.0, hours=0),
            _edge(1, 3, weight=2.0, hours=0),
        ]
        adj, strength, degree = _build_adjacency(edges, 168.0)
        assert strength[1] == 3.0
        assert degree[1] == 2


class TestPrunableEdges:
    def test_single_edge_never_pruned(self):
        """A node with degree 1 has alpha=0 (always significant)."""
        edges = [_edge(1, 2, weight=0.01, hours=500)]
        heat = {1: 0.0, 2: 0.0}
        protected = {}
        result = identify_prunable_edges(edges, heat, protected)
        assert len(result) == 0

    def test_weak_edge_among_strong_pruned(self):
        """A weak edge alongside strong edges is insignificant."""
        edges = [
            _edge(1, 2, weight=10.0, hours=0),
            _edge(1, 3, weight=10.0, hours=0),
            _edge(1, 4, weight=0.001, hours=0),  # negligible
        ]
        heat = {1: 0.5, 2: 0.5, 3: 0.5, 4: 0.01}
        protected = {}
        result = identify_prunable_edges(edges, heat, protected)
        # Edge 1-4 has p ~ 0.001/20.001 at node 1 (k=3) => alpha ~ 1.0
        # At node 4 (k=1) => alpha = 0 (significant), so kept
        # Actually node 4 has degree 1, so alpha_tgt = 0 => significant at tgt
        assert len(result) == 0

    def test_uniform_star_prunes_nothing_at_alpha_005(self):
        """Star with equal weights: alpha = (1-1/k)^{k-1} ~ 1/e for large k.
        For k=3: alpha = (2/3)^2 = 0.444 > 0.05, so edges are NOT significant.
        But each leaf has degree 1, so alpha=0 at the leaf => significant."""
        edges = [
            _edge(1, 2, weight=1.0, hours=0),
            _edge(1, 3, weight=1.0, hours=0),
            _edge(1, 4, weight=1.0, hours=0),
        ]
        heat = {1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5}
        protected = {}
        result = identify_prunable_edges(edges, heat, protected)
        # Each leaf has k=1, so alpha=0 at the leaf endpoint => kept
        assert len(result) == 0

    def test_weak_edge_between_hubs_pruned(self):
        """A weak edge connecting two high-degree hubs gets pruned."""
        # Hub 1: connected to 2,3,4,5 with strong edges, and to 6 weakly
        # Hub 6: connected to 7,8,9,10 with strong edges, and to 1 weakly
        edges = [
            _edge(1, 2, weight=10.0, hours=0),
            _edge(1, 3, weight=10.0, hours=0),
            _edge(1, 4, weight=10.0, hours=0),
            _edge(1, 5, weight=10.0, hours=0),
            _edge(1, 6, weight=0.001, hours=0),  # weak inter-hub link
            _edge(6, 7, weight=10.0, hours=0),
            _edge(6, 8, weight=10.0, hours=0),
            _edge(6, 9, weight=10.0, hours=0),
            _edge(6, 10, weight=10.0, hours=0),
        ]
        heat = {i: 0.5 for i in range(1, 11)}
        protected = {}
        result = identify_prunable_edges(edges, heat, protected)
        # Edge 1-6: at node 1, p ~ 0.001/40.001, k=5 => alpha ~ 1.0
        #           at node 6, p ~ 0.001/40.001, k=5 => alpha ~ 1.0
        # Not significant at either => pruned
        pruned_pairs = {(e["source_entity_id"], e["target_entity_id"]) for e in result}
        assert (1, 6) in pruned_pairs
        # Strong edges should not be pruned
        assert (1, 2) not in pruned_pairs

    def test_protected_entity_never_pruned(self):
        """Edges touching protected entities are always kept."""
        edges = [
            _edge(1, 2, weight=10.0, hours=0),
            _edge(1, 3, weight=10.0, hours=0),
            _edge(1, 4, weight=10.0, hours=0),
            _edge(1, 5, weight=10.0, hours=0),
            _edge(1, 6, weight=0.001, hours=0),
        ]
        heat = {i: 0.5 for i in range(1, 11)}
        protected = {1: True}
        result = identify_prunable_edges(edges, heat, protected)
        assert len(result) == 0

    def test_protected_target_prevents_prune(self):
        edges = [
            _edge(1, 2, weight=10.0, hours=0),
            _edge(1, 3, weight=10.0, hours=0),
            _edge(1, 4, weight=10.0, hours=0),
            _edge(1, 5, weight=10.0, hours=0),
            _edge(1, 6, weight=0.001, hours=0),
        ]
        heat = {i: 0.5 for i in range(1, 11)}
        protected = {6: True}
        result = identify_prunable_edges(edges, heat, protected)
        # Edge 1-6 touches protected entity 6
        assert all(e["target_entity_id"] != 6 for e in result)

    def test_temporal_decay_makes_stale_edge_prunable(self):
        """Equal raw weights but one edge is very stale => decayed weight
        becomes negligible => pruned."""
        edges = [
            _edge(1, 2, weight=1.0, hours=0),
            _edge(1, 3, weight=1.0, hours=0),
            _edge(1, 4, weight=1.0, hours=0),
            _edge(1, 5, weight=1.0, hours=2000),  # ~12 half-lives => ~0
            _edge(5, 6, weight=1.0, hours=0),
            _edge(5, 7, weight=1.0, hours=0),
            _edge(5, 8, weight=1.0, hours=0),
        ]
        heat = {i: 0.01 for i in range(1, 9)}
        protected = {}
        result = identify_prunable_edges(edges, heat, protected)
        pruned_pairs = {(e["source_entity_id"], e["target_entity_id"]) for e in result}
        assert (1, 5) in pruned_pairs

    def test_stale_reason_in_prune_metadata(self):
        """Edges pruned with high staleness include 'stale' in reasons."""
        edges = [
            _edge(1, 2, weight=1.0, hours=0),
            _edge(1, 3, weight=1.0, hours=0),
            _edge(1, 4, weight=1.0, hours=0),
            _edge(1, 5, weight=1.0, hours=2000),
            _edge(5, 6, weight=1.0, hours=0),
            _edge(5, 7, weight=1.0, hours=0),
            _edge(5, 8, weight=1.0, hours=0),
        ]
        heat = {i: 0.01 for i in range(1, 9)}
        protected = {}
        result = identify_prunable_edges(edges, heat, protected)
        stale_edges = [
            e
            for e in result
            if (e["source_entity_id"], e["target_entity_id"]) == (1, 5)
        ]
        assert len(stale_edges) == 1
        assert "stale" in stale_edges[0]["prune_reason"]
        assert "disparity_insignificant" in stale_edges[0]["prune_reason"]

    def test_empty_edges(self):
        assert identify_prunable_edges([], {}, {}) == []

    def test_cold_endpoints_reason(self):
        """Cold endpoints are tagged in prune reasons."""
        edges = [
            _edge(1, 2, weight=1.0, hours=0),
            _edge(1, 3, weight=1.0, hours=0),
            _edge(1, 4, weight=1.0, hours=0),
            _edge(1, 5, weight=1.0, hours=2000),
            _edge(5, 6, weight=1.0, hours=0),
            _edge(5, 7, weight=1.0, hours=0),
            _edge(5, 8, weight=1.0, hours=0),
        ]
        heat = {i: 0.01 for i in range(1, 9)}
        protected = {}
        result = identify_prunable_edges(edges, heat, protected)
        pruned_15 = [
            e
            for e in result
            if (e["source_entity_id"], e["target_entity_id"]) == (1, 5)
        ]
        assert len(pruned_15) == 1
        assert "cold_endpoints" in pruned_15[0]["prune_reason"]


class TestOrphanedEntities:
    def test_disconnected_cold_entity(self):
        entities = [_entity(1, heat=0.001, access_count=0)]
        result = identify_orphaned_entities(entities, set(), set())
        assert len(result) == 1

    def test_connected_entity_not_orphaned(self):
        entities = [_entity(1, heat=0.001, access_count=0)]
        result = identify_orphaned_entities(
            entities, edge_entity_ids={1}, memory_entity_ids=set()
        )
        assert len(result) == 0

    def test_mentioned_entity_not_orphaned(self):
        entities = [_entity(1, heat=0.001, access_count=0)]
        result = identify_orphaned_entities(entities, set(), memory_entity_ids={1})
        assert len(result) == 0

    def test_protected_entity_not_orphaned(self):
        entities = [_entity(1, heat=0.001, access_count=0, is_protected=True)]
        result = identify_orphaned_entities(entities, set(), set())
        assert len(result) == 0

    def test_high_access_entity_not_orphaned(self):
        entities = [_entity(1, heat=0.001, access_count=10)]
        result = identify_orphaned_entities(entities, set(), set())
        assert len(result) == 0

    def test_hot_entity_not_orphaned(self):
        entities = [_entity(1, heat=0.5, access_count=0)]
        result = identify_orphaned_entities(entities, set(), set())
        assert len(result) == 0


class TestPruningStats:
    def test_stats(self):
        edges = [
            {"prune_reason": ["disparity_insignificant", "stale"]},
            {"prune_reason": ["disparity_insignificant", "cold_endpoints"]},
        ]
        entities = [{"archive_reason": ["orphaned"]}]
        stats = compute_pruning_stats(edges, entities, 100, 50)
        assert stats["edges_to_prune"] == 2
        assert stats["entities_to_archive"] == 1
        assert stats["edge_prune_pct"] == 2.0
        assert stats["entity_archive_pct"] == 2.0
        assert stats["edge_reasons"]["disparity_insignificant"] == 2
        assert stats["edge_reasons"]["stale"] == 1

    def test_empty(self):
        stats = compute_pruning_stats([], [], 0, 0)
        assert stats["edges_to_prune"] == 0
        assert stats["entities_to_archive"] == 0
