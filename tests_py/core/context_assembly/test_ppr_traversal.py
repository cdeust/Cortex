"""Tests for mcp_server.core.context_assembly.ppr_traversal (#196).

Imported by stage_assembler.py's Phase 2 (adjacent-stage retrieval via
entity graph) but sat at 0% coverage.
"""

from __future__ import annotations

from mcp_server.core.context_assembly.ppr_traversal import (
    build_entity_adjacency,
    personalized_pagerank,
    score_memories_by_ppr,
)


class TestPersonalizedPagerank:
    def test_empty_seeds_returns_empty_dict(self):
        assert personalized_pagerank({}, {}) == {}

    def test_zero_total_seed_mass_returns_empty_dict(self):
        assert personalized_pagerank({"a": []}, {"a": 0.0}) == {}

    def test_single_isolated_seed_node_has_full_mass(self):
        result = personalized_pagerank({"a": []}, {"a": 1.0})
        assert result["a"] > 0

    def test_mass_propagates_to_neighbor(self):
        adjacency = {"a": [("b", 1.0)], "b": []}
        result = personalized_pagerank(adjacency, {"a": 1.0})
        assert "b" in result
        assert result["b"] > 0

    def test_seed_node_retains_more_mass_than_distant_neighbor(self):
        adjacency = {"a": [("b", 1.0)], "b": [("c", 1.0)], "c": []}
        result = personalized_pagerank(adjacency, {"a": 1.0}, max_iters=30)
        assert result["a"] > result.get("c", 0.0)

    def test_dangling_node_reinjects_via_seeds(self):
        # "b" has no outgoing edges — its mass must be re-injected at
        # the seed distribution rather than vanishing.
        adjacency = {"a": [("b", 1.0)], "b": []}
        result = personalized_pagerank(adjacency, {"a": 1.0}, max_iters=5)
        # Total mass across all iterations should remain bounded/positive.
        assert sum(result.values()) > 0

    def test_multiple_seeds_normalized(self):
        result = personalized_pagerank({}, {"a": 2.0, "b": 2.0})
        assert result["a"] == result["b"]

    def test_only_positive_mass_nodes_returned(self):
        adjacency = {"a": [("b", 1.0)], "b": []}
        result = personalized_pagerank(adjacency, {"a": 1.0})
        assert all(v > 0 for v in result.values())

    def test_converges_within_max_iters(self):
        adjacency = {"a": [("b", 1.0)], "b": [("a", 1.0)]}
        result = personalized_pagerank(
            adjacency, {"a": 1.0}, max_iters=100, tolerance=1e-6
        )
        assert "a" in result and "b" in result

    def test_zero_weight_edges_produce_empty_out_probs(self):
        adjacency = {"a": [("b", 0.0)], "b": []}
        result = personalized_pagerank(adjacency, {"a": 1.0}, max_iters=3)
        assert "a" in result

    def test_zero_mass_node_skipped_on_next_walk_step(self):
        # "a" has a real edge to "b" (weight 1.0) and a zero-weight edge
        # to "c". The zero-weight edge still creates a rank[c] == 0.0
        # entry (defaultdict += 0.0); the NEXT iteration's walk loop
        # must skip it via the `mass <= 0: continue` guard rather than
        # propagating a zero-mass walk step.
        adjacency = {"a": [("b", 1.0), ("c", 0.0)]}
        result = personalized_pagerank(adjacency, {"a": 1.0}, max_iters=5)
        assert result.get("c", 0.0) == 0.0


class TestBuildEntityAdjacency:
    def test_empty_inputs_returns_empty_dict(self):
        assert build_entity_adjacency([], []) == {}

    def test_entities_without_edges_are_still_nodes(self):
        entities = [{"id": "1"}, {"id": "2"}]
        adj = build_entity_adjacency(entities, [])
        assert "1" in adj and "2" in adj
        assert adj["1"] == []

    def test_uses_name_when_id_missing(self):
        entities = [{"name": "foo"}]
        adj = build_entity_adjacency(entities, [])
        assert "foo" in adj

    def test_entity_without_id_or_name_skipped(self):
        entities = [{}]
        adj = build_entity_adjacency(entities, [])
        assert adj == {}

    def test_relationship_adds_both_directions(self):
        relationships = [{"source_entity_id": "1", "target_entity_id": "2"}]
        adj = build_entity_adjacency([], relationships)
        assert ("2", 1.0) in adj["1"]
        assert ("1", 1.0) in adj["2"]

    def test_relationship_uses_strength_field(self):
        relationships = [
            {"source_entity_id": "1", "target_entity_id": "2", "strength": 3.5}
        ]
        adj = build_entity_adjacency([], relationships)
        assert ("2", 3.5) in adj["1"]

    def test_relationship_fallback_source_target_fields(self):
        relationships = [{"source": "a", "target": "b"}]
        adj = build_entity_adjacency([], relationships)
        assert ("b", 1.0) in adj["a"]

    def test_zero_or_negative_strength_relationship_excluded(self):
        relationships = [
            {"source_entity_id": "1", "target_entity_id": "2", "strength": 0.0}
        ]
        adj = build_entity_adjacency([], relationships)
        assert adj == {}

    def test_relationship_missing_endpoint_excluded(self):
        relationships = [{"source_entity_id": "1"}]  # no target
        adj = build_entity_adjacency([], relationships)
        assert adj == {}


class TestScoreMemoriesByPpr:
    def test_empty_memories_returns_empty_list(self):
        assert score_memories_by_ppr([], {}) == []

    def test_memory_without_entities_excluded(self):
        memories = [{"id": 1, "entity_ids": []}]
        assert score_memories_by_ppr(memories, {}) == []

    def test_memory_missing_entity_ids_key_excluded(self):
        memories = [{"id": 1}]
        assert score_memories_by_ppr(memories, {"e1": 0.5}) == []

    def test_aggregates_mass_across_entities(self):
        memories = [{"id": 1, "entity_ids": ["e1", "e2"]}]
        ppr_scores = {"e1": 0.3, "e2": 0.2}
        result = score_memories_by_ppr(memories, ppr_scores)
        assert result == [(memories[0], 0.5)]

    def test_sorted_descending_by_score(self):
        memories = [
            {"id": 1, "entity_ids": ["e1"]},
            {"id": 2, "entity_ids": ["e2"]},
        ]
        ppr_scores = {"e1": 0.1, "e2": 0.9}
        result = score_memories_by_ppr(memories, ppr_scores)
        assert [m["id"] for m, _ in result] == [2, 1]

    def test_unknown_entity_id_contributes_zero_mass(self):
        memories = [{"id": 1, "entity_ids": ["unknown"]}]
        result = score_memories_by_ppr(memories, {"e1": 0.5})
        assert result == []

    def test_custom_entity_ids_key(self):
        memories = [{"id": 1, "ents": ["e1"]}]
        result = score_memories_by_ppr(memories, {"e1": 0.5}, entity_ids_key="ents")
        assert result == [(memories[0], 0.5)]
