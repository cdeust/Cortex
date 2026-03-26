"""Tests for mcp_server.core.retrieval_dispatch — 3-tier dispatch."""

from mcp_server.core.retrieval_dispatch import (
    classify_tier,
    wrrf_fuse,
    compute_signal_weights,
    merge_multihop_results,
    dispatch_retrieval,
)
from mcp_server.core.query_intent import QueryIntent, classify_query_intent


class TestClassifyTier:
    def test_general_is_simple(self):
        assert classify_tier(QueryIntent.GENERAL) == "simple"

    def test_temporal_is_simple(self):
        assert classify_tier(QueryIntent.TEMPORAL) == "simple"

    def test_knowledge_update_is_simple(self):
        assert classify_tier(QueryIntent.KNOWLEDGE_UPDATE) == "simple"

    def test_multi_hop_is_mixed(self):
        assert classify_tier(QueryIntent.MULTI_HOP) == "mixed"

    def test_entity_is_deep(self):
        assert classify_tier(QueryIntent.ENTITY) == "deep"

    def test_instruction_is_deep(self):
        assert classify_tier(QueryIntent.INSTRUCTION) == "deep"


class TestWRRFFuse:
    def test_single_signal(self):
        results = wrrf_fuse(
            [[(1, 0.9), (2, 0.8), (3, 0.7)]],
            [1.0],
            k=60,
        )
        assert results[0][0] == 1  # Highest rank first

    def test_multi_signal(self):
        results = wrrf_fuse(
            [[(1, 0.9), (2, 0.5)], [(2, 0.9), (3, 0.5)]],
            [1.0, 1.0],
            k=60,
        )
        # doc 2 appears in both signals, should score highest
        ids = [r[0] for r in results]
        assert ids[0] == 2

    def test_empty(self):
        assert wrrf_fuse([], [], k=60) == []

    def test_zero_weight_ignored(self):
        results = wrrf_fuse([[(1, 0.9)]], [0.0], k=60)
        assert results == []


class TestComputeSignalWeights:
    def test_simple_tier(self):
        weights = compute_signal_weights(
            "simple", {"vector": 1.0, "fts": 1.0, "heat": 1.0}
        )
        assert "vector" in weights
        assert "bm25" in weights
        assert "ngram" in weights

    def test_deep_tier_boosts_bm25(self):
        simple_w = compute_signal_weights("simple", {"fts": 1.0})
        deep_w = compute_signal_weights("deep", {"fts": 1.0})
        assert deep_w["bm25"] > simple_w["bm25"]

    def test_deep_tier_boosts_sa(self):
        simple_w = compute_signal_weights("simple", {"spreading": 1.0, "fts": 1.0})
        deep_w = compute_signal_weights("deep", {"spreading": 1.0, "fts": 1.0})
        assert deep_w["sa"] > simple_w["sa"]

    def test_instruction_intent_boosts_bm25_over_deep(self):
        deep_w = compute_signal_weights("deep", {"fts": 1.0})
        instr_w = compute_signal_weights(
            "deep", {"fts": 1.0}, intent=QueryIntent.INSTRUCTION
        )
        assert instr_w["bm25"] > deep_w["bm25"]

    def test_instruction_intent_reduces_vector(self):
        simple_w = compute_signal_weights("simple", {"vector": 1.0})
        instr_w = compute_signal_weights(
            "deep", {"vector": 1.0}, intent=QueryIntent.INSTRUCTION
        )
        assert instr_w["vector"] < simple_w["vector"]


class TestMergeMultihopResults:
    def test_reinforcement(self):
        primary = [(1, 1.0), (2, 0.5)]
        secondary = [(2, 0.8), (3, 0.6)]
        merged = merge_multihop_results(primary, secondary, hop_weight=0.3)
        # doc 2 should be reinforced
        scores = {mid: s for mid, s in merged}
        assert scores[2] > 0.5  # Original was 0.5, should increase
        assert 3 in scores  # New doc added

    def test_empty_secondary(self):
        primary = [(1, 1.0)]
        merged = merge_multihop_results(primary, [], hop_weight=0.3)
        assert merged == primary


class TestDispatchRetrieval:
    def test_simple_dispatch(self):
        signals = {
            "vector": [(1, 0.9), (2, 0.5)],
            "fts": [(1, 0.8), (3, 0.3)],
        }
        intent_info = classify_query_intent("what is my favorite color")
        fused, tier = dispatch_retrieval(
            query="what is my favorite color",
            signals=signals,
            intent_info=intent_info,
            content_lookup={1: "I like blue", 2: "Weather is nice", 3: "Red is great"},
        )
        assert tier in ("simple", "deep")
        assert len(fused) > 0

    def test_mixed_dispatch_with_hop(self):
        signals = {"vector": [(1, 0.9)], "fts": [(1, 0.8)]}
        intent_info = {"intent": QueryIntent.MULTI_HOP, "weights": {}}
        hop_called = []

        def mock_hop(sub_q):
            hop_called.append(sub_q)
            return [(2, 0.5)]

        fused, tier = dispatch_retrieval(
            query="Compare Alice and Bob",
            signals=signals,
            intent_info=intent_info,
            content_lookup={1: "Alice works here", 2: "Bob works there"},
            hop_fn=mock_hop,
        )
        assert tier == "mixed"
