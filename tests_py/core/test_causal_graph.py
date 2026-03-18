"""Tests for mcp_server.core.causal_graph — PC algorithm causal edge discovery."""

from mcp_server.core.causal_graph import (
    compute_co_occurrence_matrix,
    compute_conditional_independence,
    compute_temporal_precedence,
    discover_causal_edges,
    find_causal_chain,
    find_common_causes,
)


# ── compute_co_occurrence_matrix ─────────────────────────────────────────


class TestComputeCoOccurrenceMatrix:
    def test_empty_memories(self):
        assert compute_co_occurrence_matrix([], ["A", "B"]) == {}

    def test_empty_entities(self):
        mems = [{"content": "hello world"}]
        assert compute_co_occurrence_matrix(mems, []) == {}

    def test_single_entity_no_pairs(self):
        mems = [{"content": "mentions A only"}]
        assert compute_co_occurrence_matrix(mems, ["A"]) == {}

    def test_two_entities_co_occur(self):
        mems = [{"content": "A and B together"}]
        result = compute_co_occurrence_matrix(mems, ["A", "B"])
        assert result[("A", "B")] == 1

    def test_sorted_key_order(self):
        mems = [{"content": "Z and A appear"}]
        result = compute_co_occurrence_matrix(mems, ["Z", "A"])
        assert ("A", "Z") in result
        assert ("Z", "A") not in result

    def test_multiple_memories_accumulate(self):
        mems = [
            {"content": "A and B"},
            {"content": "A and B again"},
            {"content": "only A here"},
        ]
        result = compute_co_occurrence_matrix(mems, ["A", "B"])
        assert result[("A", "B")] == 2

    def test_three_entities_all_pairs(self):
        mems = [{"content": "A B C all present"}]
        result = compute_co_occurrence_matrix(mems, ["A", "B", "C"])
        assert len(result) == 3  # (A,B), (A,C), (B,C)

    def test_case_insensitive_matching(self):
        mems = [{"content": "apple and banana"}]
        result = compute_co_occurrence_matrix(mems, ["Apple", "Banana"])
        assert result[("Apple", "Banana")] == 1

    def test_missing_content_key(self):
        mems = [{"tags": ["test"]}]
        result = compute_co_occurrence_matrix(mems, ["A", "B"])
        assert result == {}


# ── compute_conditional_independence ─────────────────────────────────────


class TestComputeConditionalIndependence:
    def test_zero_total_returns_zero(self):
        assert compute_conditional_independence(5, 10, 10, 0) == 0.0

    def test_zero_a_count_returns_zero(self):
        assert compute_conditional_independence(5, 0, 10, 100) == 0.0

    def test_zero_b_count_returns_zero(self):
        assert compute_conditional_independence(5, 10, 0, 100) == 0.0

    def test_zero_pair_count_negative_pmi(self):
        result = compute_conditional_independence(0, 10, 10, 100)
        assert result == -10.0

    def test_perfect_co_occurrence_positive_pmi(self):
        # A and B always appear together: p_ab = p_a = p_b = 1.0
        result = compute_conditional_independence(100, 100, 100, 100)
        assert result == 0.0  # log2(1.0 / 1.0) = 0

    def test_strong_positive_association(self):
        # A appears 10/100, B appears 10/100, pair appears 10/100
        # p_ab = 0.1, p_a*p_b = 0.01, PMI = log2(10)
        result = compute_conditional_independence(10, 10, 10, 100)
        assert result > 3.0  # log2(10) ≈ 3.32

    def test_conditioning_reduces_pmi(self):
        base = compute_conditional_independence(10, 10, 10, 100, conditioned_count=0)
        conditioned = compute_conditional_independence(
            10, 10, 10, 100, conditioned_count=5
        )
        assert conditioned < base

    def test_full_conditioning_zeroes_pmi(self):
        result = compute_conditional_independence(10, 10, 10, 100, conditioned_count=10)
        assert result == 0.0


# ── compute_temporal_precedence ──────────────────────────────────────────


class TestComputeTemporalPrecedence:
    def test_a_before_b(self):
        first_seen = {"A": "2026-01-01", "B": "2026-01-02"}
        assert compute_temporal_precedence(first_seen, "A", "B") == "a_before_b"

    def test_b_before_a(self):
        first_seen = {"A": "2026-01-02", "B": "2026-01-01"}
        assert compute_temporal_precedence(first_seen, "A", "B") == "b_before_a"

    def test_same_time_returns_none(self):
        first_seen = {"A": "2026-01-01", "B": "2026-01-01"}
        assert compute_temporal_precedence(first_seen, "A", "B") is None

    def test_missing_a_returns_none(self):
        assert compute_temporal_precedence({"B": "2026-01-01"}, "A", "B") is None

    def test_missing_b_returns_none(self):
        assert compute_temporal_precedence({"A": "2026-01-01"}, "A", "B") is None

    def test_empty_dict_returns_none(self):
        assert compute_temporal_precedence({}, "A", "B") is None


# ── discover_causal_edges ────────────────────────────────────────────────


class TestDiscoverCausalEdges:
    def test_empty_entities(self):
        assert discover_causal_edges([], {}, {}, 100) == []

    def test_zero_memories(self):
        assert discover_causal_edges(["A"], {}, {}, 0) == []

    def test_below_min_observations_filtered(self):
        co = {("A", "B"): 2}  # Below default min_observations=3
        counts = {"A": 10, "B": 10}
        result = discover_causal_edges(["A", "B"], co, counts, 100)
        assert result == []

    def test_independent_pair_filtered(self):
        # Low co-occurrence relative to individual counts
        co = {("A", "B"): 5}
        counts = {"A": 90, "B": 90}
        result = discover_causal_edges(
            ["A", "B"], co, counts, 100, independence_threshold=0.5, min_observations=3
        )
        assert len(result) == 0

    def test_strongly_associated_pair_kept(self):
        co = {("A", "B"): 10}
        counts = {"A": 10, "B": 10}
        result = discover_causal_edges(
            ["A", "B"], co, counts, 100, independence_threshold=0.5, min_observations=3
        )
        assert len(result) == 1
        assert result[0]["strength"] > 0

    def test_temporal_precedence_orients_edge(self):
        co = {("A", "B"): 10}
        counts = {"A": 10, "B": 10}
        first_seen = {"A": "2026-01-01", "B": "2026-01-02"}
        result = discover_causal_edges(
            ["A", "B"],
            co,
            counts,
            100,
            entity_first_seen=first_seen,
            min_observations=3,
        )
        assert len(result) == 1
        assert result[0]["source"] == "A"
        assert result[0]["target"] == "B"
        assert result[0]["is_directed"] is True

    def test_no_temporal_reduces_strength(self):
        co = {("A", "B"): 10}
        counts = {"A": 10, "B": 10}
        directed = discover_causal_edges(
            ["A", "B"],
            co,
            counts,
            100,
            entity_first_seen={"A": "2026-01-01", "B": "2026-01-02"},
            min_observations=3,
        )
        undirected = discover_causal_edges(
            ["A", "B"],
            co,
            counts,
            100,
            entity_first_seen=None,
            min_observations=3,
        )
        if directed and undirected:
            assert undirected[0]["strength"] < directed[0]["strength"]

    def test_conditional_independence_removes_edge(self):
        # A-B co-occur, but C explains both
        co = {("A", "B"): 5, ("A", "C"): 10, ("B", "C"): 10}
        counts = {"A": 15, "B": 15, "C": 20}
        result = discover_causal_edges(
            ["A", "B", "C"],
            co,
            counts,
            100,
            independence_threshold=0.5,
            min_observations=3,
        )
        # A-B should be removed or weakened due to C explaining it
        ab_edges = [e for e in result if {e["source"], e["target"]} == {"A", "B"}]
        # The conditioning should remove A-B since C explains both
        assert len(ab_edges) == 0

    def test_sorted_by_strength(self):
        co = {("A", "B"): 10, ("C", "D"): 20}
        counts = {"A": 10, "B": 10, "C": 20, "D": 20}
        result = discover_causal_edges(
            ["A", "B", "C", "D"],
            co,
            counts,
            100,
            min_observations=3,
        )
        if len(result) >= 2:
            assert result[0]["strength"] >= result[1]["strength"]


# ── find_causal_chain ────────────────────────────────────────────────────


class TestFindCausalChain:
    def test_empty_edges(self):
        assert find_causal_chain([], "A") == []

    def test_start_not_in_graph(self):
        edges = [{"source": "X", "target": "Y", "is_directed": True}]
        assert find_causal_chain(edges, "A") == []

    def test_single_directed_edge(self):
        edges = [{"source": "A", "target": "B", "is_directed": True}]
        paths = find_causal_chain(edges, "A")
        assert len(paths) >= 1
        assert ["A", "B"] in paths

    def test_chain_of_three(self):
        edges = [
            {"source": "A", "target": "B", "is_directed": True},
            {"source": "B", "target": "C", "is_directed": True},
        ]
        paths = find_causal_chain(edges, "A")
        assert any(len(p) == 3 and p[0] == "A" and p[-1] == "C" for p in paths)

    def test_max_depth_limits(self):
        edges = [
            {"source": "A", "target": "B", "is_directed": True},
            {"source": "B", "target": "C", "is_directed": True},
            {"source": "C", "target": "D", "is_directed": True},
        ]
        paths = find_causal_chain(edges, "A", max_depth=2)
        assert all(len(p) <= 3 for p in paths)  # max_depth=2 → 3 nodes max

    def test_cycle_avoided(self):
        edges = [
            {"source": "A", "target": "B", "is_directed": True},
            {"source": "B", "target": "A", "is_directed": True},
        ]
        paths = find_causal_chain(edges, "A")
        for p in paths:
            assert len(p) == len(set(p))  # No duplicates

    def test_undirected_edges_ignored(self):
        edges = [{"source": "A", "target": "B", "is_directed": False}]
        assert find_causal_chain(edges, "A") == []


# ── find_common_causes ───────────────────────────────────────────────────


class TestFindCommonCauses:
    def test_empty_edges(self):
        assert find_common_causes([], "A", "B") == []

    def test_no_common_causes(self):
        edges = [
            {"source": "X", "target": "A", "is_directed": True},
            {"source": "Y", "target": "B", "is_directed": True},
        ]
        assert find_common_causes(edges, "A", "B") == []

    def test_one_common_cause(self):
        edges = [
            {"source": "C", "target": "A", "is_directed": True},
            {"source": "C", "target": "B", "is_directed": True},
        ]
        result = find_common_causes(edges, "A", "B")
        assert result == ["C"]

    def test_multiple_common_causes(self):
        edges = [
            {"source": "C", "target": "A", "is_directed": True},
            {"source": "C", "target": "B", "is_directed": True},
            {"source": "D", "target": "A", "is_directed": True},
            {"source": "D", "target": "B", "is_directed": True},
        ]
        result = find_common_causes(edges, "A", "B")
        assert result == ["C", "D"]

    def test_undirected_edges_ignored(self):
        edges = [
            {"source": "C", "target": "A", "is_directed": False},
            {"source": "C", "target": "B", "is_directed": False},
        ]
        assert find_common_causes(edges, "A", "B") == []

    def test_sorted_output(self):
        edges = [
            {"source": "Z", "target": "A", "is_directed": True},
            {"source": "Z", "target": "B", "is_directed": True},
            {"source": "M", "target": "A", "is_directed": True},
            {"source": "M", "target": "B", "is_directed": True},
        ]
        result = find_common_causes(edges, "A", "B")
        assert result == sorted(result)
