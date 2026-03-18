"""Tests for mcp_server.core.reranker — FlashRank cross-encoder."""

from unittest.mock import patch

from mcp_server.core.reranker import rerank_results


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
