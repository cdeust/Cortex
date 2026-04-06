"""Tests for MMR diversity reranking (Carbonell & Goldstein, SIGIR 1998)."""

import numpy as np

from mcp_server.core.mmr_diversity import mmr_rerank


def _make_candidate(vec: list[float], score: float = 1.0) -> dict:
    return {
        "memory_id": id(vec),
        "content": "test",
        "score": score,
        "embedding": np.array(vec, dtype=np.float32).tobytes(),
    }


def _make_query(vec: list[float]) -> bytes:
    return np.array(vec, dtype=np.float32).tobytes()


class TestMMRRerank:
    def test_empty_candidates(self):
        result = mmr_rerank([], _make_query([1, 0, 0]))
        assert result == []

    def test_single_candidate(self):
        c = [_make_candidate([1, 0, 0])]
        result = mmr_rerank(c, _make_query([1, 0, 0]))
        assert len(result) == 1

    def test_no_query_embedding(self):
        c = [_make_candidate([1, 0, 0]), _make_candidate([0, 1, 0])]
        result = mmr_rerank(c, None)
        assert len(result) == 2

    def test_selects_diverse_over_redundant(self):
        """Given 3 candidates where 2 are near-identical, MMR should
        prefer the diverse one over the redundant copy."""
        q = _make_query([1, 0, 0])
        c1 = _make_candidate([0.9, 0.1, 0])  # Close to query
        c2 = _make_candidate([0.85, 0.15, 0])  # Near-duplicate of c1
        c3 = _make_candidate([0.5, 0.5, 0.7])  # Different direction
        result = mmr_rerank([c1, c2, c3], q, lambda_param=0.5, top_k=2)
        # First should be c1 (most relevant), second should be c3 (diverse)
        assert len(result) == 2
        assert result[0]["memory_id"] == c1["memory_id"]
        assert result[1]["memory_id"] == c3["memory_id"]

    def test_lambda_1_is_pure_relevance(self):
        """lambda=1.0 should return in relevance order (no diversity)."""
        q = _make_query([1, 0, 0])
        c1 = _make_candidate([0.9, 0.1, 0])
        c2 = _make_candidate([0.85, 0.15, 0])
        c3 = _make_candidate([0.5, 0.5, 0.7])
        result = mmr_rerank([c1, c2, c3], q, lambda_param=1.0, top_k=3)
        # Pure relevance: c1 > c2 > c3 (by cosine to query)
        assert result[0]["memory_id"] == c1["memory_id"]
        assert result[1]["memory_id"] == c2["memory_id"]

    def test_lambda_0_is_pure_diversity(self):
        """lambda=0.0 should maximize diversity."""
        q = _make_query([1, 0, 0])
        c1 = _make_candidate([0.9, 0.1, 0])
        c2 = _make_candidate([0.85, 0.15, 0])
        c3 = _make_candidate([0, 0, 1])  # Orthogonal
        result = mmr_rerank([c1, c2, c3], q, lambda_param=0.0, top_k=3)
        # First pick has no selected set, so MMR=0 for all (first by order)
        # Second pick: c3 is most different from first pick
        assert result[1]["memory_id"] == c3["memory_id"]

    def test_top_k_respected(self):
        candidates = [_make_candidate([i, 0, 0]) for i in range(10)]
        result = mmr_rerank(candidates, _make_query([1, 0, 0]), top_k=3)
        assert len(result) == 3

    def test_missing_embeddings_handled(self):
        """Candidates without embeddings should be skipped gracefully."""
        c1 = _make_candidate([1, 0, 0])
        c2 = {"memory_id": 999, "content": "no embedding", "score": 0.5}
        result = mmr_rerank([c1, c2], _make_query([1, 0, 0]))
        assert len(result) >= 1
