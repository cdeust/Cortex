"""Tests for mcp_server.core.spreading_activation — Collins & Loftus semantic priming."""

import pytest

from mcp_server.core.spreading_activation import (
    spread_activation,
    map_entity_activation_to_memories,
    resolve_seed_entities,
    build_entity_graph,
)


class TestSpreadActivation:
    def test_single_seed_no_neighbors(self):
        graph = {1: []}
        result = spread_activation(graph, [1])
        assert result == {1: 1.0}

    def test_single_hop(self):
        graph = {1: [(2, 1.0)], 2: [(1, 1.0)]}
        result = spread_activation(graph, [1], decay=0.5, max_depth=1)
        assert result[1] == 1.0
        assert result[2] == pytest.approx(0.5, abs=1e-6)

    def test_convergent_activation(self):
        """Node reached from two parents gets summed activation."""
        graph = {
            1: [(3, 1.0)],
            2: [(3, 1.0)],
            3: [(1, 1.0), (2, 1.0)],
        }
        result = spread_activation(graph, [1, 2], decay=0.5, max_depth=1)
        assert result[3] == pytest.approx(1.0, abs=1e-6)  # 0.5 + 0.5

    def test_decay_across_hops(self):
        graph = {
            1: [(2, 1.0)],
            2: [(1, 1.0), (3, 1.0)],
            3: [(2, 1.0)],
        }
        result = spread_activation(graph, [1], decay=0.5, max_depth=2)
        assert 1 in result and 2 in result and 3 in result
        assert result[2] > result[3]

    def test_threshold_prunes(self):
        graph = {
            1: [(2, 0.1)],
            2: [(1, 0.1), (3, 1.0)],
            3: [(2, 1.0)],
        }
        result = spread_activation(graph, [1], decay=0.5, threshold=0.2, max_depth=2)
        # 1->2: 1.0 * 0.1 * 0.5 = 0.05 < threshold
        assert 3 not in result

    def test_max_nodes_cap(self):
        graph = {}
        for i in range(50):
            graph[i] = [(i + 1, 1.0)]
            graph[i + 1] = graph.get(i + 1, [])
            graph[i + 1].append((i, 1.0))
        result = spread_activation(graph, [0], decay=0.9, max_depth=10, max_nodes=5)
        assert len(result) <= 5

    def test_edge_weight_matters(self):
        graph = {
            1: [(2, 1.0), (3, 0.1)],
            2: [(1, 1.0)],
            3: [(1, 0.1)],
        }
        result = spread_activation(graph, [1], decay=0.5, max_depth=1)
        assert result[2] > result[3]

    def test_empty_graph(self):
        assert spread_activation({}, [1]) == {}

    def test_seed_not_in_graph(self):
        graph = {2: [(3, 1.0)], 3: [(2, 1.0)]}
        assert spread_activation(graph, [999]) == {}

    def test_multiple_seeds(self):
        graph = {
            1: [(3, 1.0)],
            2: [(4, 1.0)],
            3: [(1, 1.0)],
            4: [(2, 1.0)],
        }
        result = spread_activation(graph, [1, 2], decay=0.5, max_depth=1)
        assert 1 in result and 2 in result and 3 in result and 4 in result

    def test_self_loops_handled(self):
        graph = {1: [(1, 1.0), (2, 1.0)], 2: [(1, 1.0)]}
        result = spread_activation(graph, [1], decay=0.5, max_depth=1)
        assert 2 in result

    def test_zero_decay_returns_only_seeds(self):
        graph = {1: [(2, 1.0)], 2: [(1, 1.0)]}
        result = spread_activation(graph, [1], decay=0.0, max_depth=3)
        assert result == {1: 1.0}

    def test_high_threshold_limits_spread(self):
        graph = {1: [(2, 0.5)], 2: [(1, 0.5), (3, 1.0)], 3: [(2, 1.0)]}
        result = spread_activation(graph, [1], decay=0.5, threshold=0.5, max_depth=3)
        # 1->2: 1.0 * 0.5 * 0.5 = 0.25 < 0.5 threshold, no propagation
        assert 3 not in result


class TestMapEntityToMemories:
    def test_basic_mapping(self):
        activations = {1: 0.8, 2: 0.5}
        entity_to_mems = {1: [100, 101], 2: [101, 102]}
        result = dict(map_entity_activation_to_memories(activations, entity_to_mems))
        assert result[100] == 0.8
        assert result[101] == 0.8  # max(0.8, 0.5)
        assert result[102] == 0.5

    def test_empty_activations(self):
        assert map_entity_activation_to_memories({}, {1: [100]}) == []

    def test_no_memory_links(self):
        assert map_entity_activation_to_memories({1: 0.5}, {}) == []

    def test_sorted_descending(self):
        activations = {1: 0.3, 2: 0.9}
        entity_to_mems = {1: [100], 2: [200]}
        result = map_entity_activation_to_memories(activations, entity_to_mems)
        assert result[0][0] == 200  # highest first
        assert result[1][0] == 100

    def test_max_aggregation(self):
        """Memory linked to two entities gets the max, not sum."""
        activations = {1: 0.3, 2: 0.7}
        entity_to_mems = {1: [100], 2: [100]}
        result = dict(map_entity_activation_to_memories(activations, entity_to_mems))
        assert result[100] == 0.7  # max, not 1.0


class TestResolveSeedEntities:
    def test_case_insensitive(self):
        index = {"sqlite": 1, "python": 2}
        assert resolve_seed_entities(["SQLite", "Python"], index) == [1, 2]

    def test_unmatched_skipped(self):
        index = {"sqlite": 1}
        assert resolve_seed_entities(["sqlite", "unknown"], index) == [1]

    def test_deduplication(self):
        index = {"sqlite": 1}
        result = resolve_seed_entities(["sqlite", "SQLite"], index)
        assert result == [1]

    def test_empty(self):
        assert resolve_seed_entities([], {"a": 1}) == []

    def test_empty_index(self):
        assert resolve_seed_entities(["foo"], {}) == []


class TestBuildEntityGraph:
    def test_basic_graph(self):
        entities = [
            {"id": 1, "name": "Foo", "heat": 0.5},
            {"id": 2, "name": "Bar", "heat": 0.5},
        ]
        relationships = [
            {
                "source_entity_id": 1,
                "target_entity_id": 2,
                "weight": 0.8,
                "confidence": 1.0,
            },
        ]
        graph, index = build_entity_graph(entities, relationships)
        assert 1 in graph and 2 in graph
        assert (2, 0.8) in graph[1]
        assert (1, 0.8) in graph[2]  # bidirectional
        assert index["foo"] == 1
        assert index["bar"] == 2

    def test_heat_filter(self):
        entities = [
            {"id": 1, "name": "Hot", "heat": 0.8},
            {"id": 2, "name": "Cold", "heat": 0.01},
        ]
        relationships = [
            {"source_entity_id": 1, "target_entity_id": 2, "weight": 1.0},
        ]
        graph, index = build_entity_graph(entities, relationships, min_heat=0.1)
        assert "cold" not in index
        assert 2 not in graph.get(1, [])

    def test_empty_inputs(self):
        graph, index = build_entity_graph([], [])
        assert graph == {}
        assert index == {}

    def test_weight_times_confidence(self):
        entities = [
            {"id": 1, "name": "A", "heat": 1.0},
            {"id": 2, "name": "B", "heat": 1.0},
        ]
        relationships = [
            {
                "source_entity_id": 1,
                "target_entity_id": 2,
                "weight": 0.6,
                "confidence": 0.5,
            }
        ]
        graph, _ = build_entity_graph(entities, relationships)
        assert graph[1][0][1] == pytest.approx(0.3)  # 0.6 * 0.5
