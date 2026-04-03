"""Tests for mcp_server.core.reranker — FlashRank cross-encoder + confidence."""

from unittest.mock import patch

from mcp_server.core.reranker import (
    _compute_retrieval_confidence,
    _blend_scores,
    rerank_results,
)


class TestRetrievalConfidence:
    """Tests for Sufficient Context confidence gating (binary gate)."""

    def test_high_ce_scores_give_full_confidence(self):
        confidence = _compute_retrieval_confidence([0.8, 0.6, 0.3])
        assert confidence == 1.0

    def test_above_gate_gives_full_confidence(self):
        confidence = _compute_retrieval_confidence([0.2, 0.1])
        assert confidence == 1.0

    def test_below_gate_gives_suppression(self):
        confidence = _compute_retrieval_confidence([0.1, 0.05])
        assert confidence == 0.1

    def test_empty_scores_return_suppression(self):
        confidence = _compute_retrieval_confidence([])
        assert confidence == 0.1

    def test_negative_scores_give_suppression(self):
        confidence = _compute_retrieval_confidence([-1.0, -0.5])
        assert confidence == 0.1

    def test_custom_gate_threshold(self):
        confidence = _compute_retrieval_confidence([0.3], gate_threshold=0.5)
        assert confidence < 1.0

    def test_at_threshold_gives_full_confidence(self):
        confidence = _compute_retrieval_confidence([0.15])
        assert confidence == 1.0


class TestBlendScoresWithConfidence:
    def test_high_confidence_preserves_scores(self):
        candidates = [(1, 0.5), (2, 0.3)]
        ce_scores = {0: 0.9, 1: 0.7}
        result = _blend_scores(candidates, ce_scores, alpha=0.55)
        # High CE → high confidence → scores close to raw blended
        top_score = result[0][1]
        assert top_score > 0.5

    def test_low_confidence_suppresses_scores(self):
        candidates = [(1, 0.5), (2, 0.3)]
        ce_scores = {0: 0.05, 1: 0.02}
        result = _blend_scores(candidates, ce_scores, alpha=0.55)
        # Low CE → low confidence → scores pulled down
        top_score = result[0][1]
        assert top_score < 0.3


class TestReranker:
    def test_passthrough_without_flashrank(self):
        """When FlashRank unavailable, returns original order."""
        candidates = [(1, 0.9), (2, 0.5), (3, 0.3)]
        with patch("mcp_server.core.reranker._ensure_reranker", return_value=None):
            result = rerank_results("test", candidates, {1: "a", 2: "b", 3: "c"})
        assert result == candidates

    def test_empty_candidates(self):
        result = rerank_results("test", [], {})
        assert result == []

    def test_empty_content_lookup(self):
        candidates = [(1, 0.9)]
        with patch("mcp_server.core.reranker._ensure_reranker", return_value=None):
            result = rerank_results("test", candidates, {})
        assert result == candidates
