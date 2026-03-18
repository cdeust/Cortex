"""Tests for mcp_server.core.microglial_pruning — complement-dependent elimination."""

from mcp_server.core.microglial_pruning import (
    identify_prunable_edges,
    identify_orphaned_entities,
    compute_pruning_stats,
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


class TestPrunableEdges:
    def test_low_weight_stale_cold_pruned(self):
        edges = [_edge(1, 2, weight=0.01, hours=200)]
        heat = {1: 0.05, 2: 0.05}
        protected = {1: False, 2: False}
        result = identify_prunable_edges(edges, heat, protected)
        assert len(result) == 1
        assert "low_weight" in result[0]["prune_reason"]

    def test_protected_entity_not_pruned(self):
        edges = [_edge(1, 2, weight=0.01, hours=200)]
        heat = {1: 0.05, 2: 0.05}
        protected = {1: True, 2: False}
        result = identify_prunable_edges(edges, heat, protected)
        assert len(result) == 0

    def test_high_weight_fresh_hot_not_pruned(self):
        edges = [_edge(1, 2, weight=0.5, hours=10)]
        heat = {1: 0.5, 2: 0.5}
        protected = {}
        result = identify_prunable_edges(edges, heat, protected)
        assert len(result) == 0

    def test_hot_endpoints_only_one_signal(self):
        # low_weight but hot endpoints and fresh → only 1 signal (low_weight), needs 2
        edges = [_edge(1, 2, weight=0.01, hours=10)]
        heat = {1: 0.5, 2: 0.5}
        protected = {}
        result = identify_prunable_edges(edges, heat, protected)
        assert len(result) == 0

    def test_needs_two_signals(self):
        # Only one signal (stale but weight ok)
        edges = [_edge(1, 2, weight=0.1, hours=200)]
        heat = {1: 0.05, 2: 0.05}
        protected = {}
        result = identify_prunable_edges(edges, heat, protected)
        # stale + cold_endpoints = 2 signals
        assert len(result) == 1

    def test_fresh_low_weight_one_signal(self):
        # low_weight only (not stale, not cold)
        edges = [_edge(1, 2, weight=0.01, hours=10)]
        heat = {1: 0.5, 2: 0.5}
        protected = {}
        result = identify_prunable_edges(edges, heat, protected)
        assert len(result) == 0


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
            {"prune_reason": ["low_weight", "stale"]},
            {"prune_reason": ["stale", "cold_endpoints"]},
        ]
        entities = [{"archive_reason": ["orphaned"]}]
        stats = compute_pruning_stats(edges, entities, 100, 50)
        assert stats["edges_to_prune"] == 2
        assert stats["entities_to_archive"] == 1
        assert stats["edge_prune_pct"] == 2.0
        assert stats["entity_archive_pct"] == 2.0
        assert stats["edge_reasons"]["stale"] == 2
        assert stats["edge_reasons"]["low_weight"] == 1

    def test_empty(self):
        stats = compute_pruning_stats([], [], 0, 0)
        assert stats["edges_to_prune"] == 0
        assert stats["entities_to_archive"] == 0
