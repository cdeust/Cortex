"""Tests for mcp_server.core.context_assembly.coverage.submodular_select
(#196). Imported by stage_assembler.py (Phase 1) but sat at 0% coverage."""

from __future__ import annotations

import numpy as np

from mcp_server.core.context_assembly.coverage import submodular_select


class TestSubmodularSelectBasics:
    def test_empty_candidates_returns_empty(self):
        assert submodular_select([], token_budget=None) == []

    def test_selects_up_to_max_chunks(self):
        candidates = [{"score": float(i), "content": "x"} for i in range(10)]
        result = submodular_select(candidates, token_budget=None, max_chunks=3)
        assert len(result) == 3

    def test_fewer_candidates_than_max_chunks_returns_all(self):
        candidates = [{"score": 1.0, "content": "x"} for _ in range(2)]
        result = submodular_select(candidates, token_budget=None, max_chunks=5)
        assert len(result) == 2

    def test_highest_score_selected_first_without_diversity(self):
        candidates = [
            {"score": 0.1, "content": "a"},
            {"score": 0.9, "content": "b"},
            {"score": 0.5, "content": "c"},
        ]
        result = submodular_select(
            candidates, token_budget=None, max_chunks=1, diversity_lambda=0.0
        )
        assert result == [{"score": 0.9, "content": "b"}]

    def test_result_preserves_original_ranking_order(self):
        candidates = [
            {"score": 0.5, "content": "a"},
            {"score": 0.9, "content": "b"},
            {"score": 0.1, "content": "c"},
        ]
        result = submodular_select(
            candidates, token_budget=None, max_chunks=2, diversity_lambda=0.0
        )
        # Selected are indices 0 and 1 (highest two scores); original order.
        assert [c["content"] for c in result] == ["a", "b"]


class TestSubmodularSelectTokenBudget:
    def test_token_budget_none_ignores_size(self):
        candidates = [{"score": 1.0, "content": "x" * 3000} for _ in range(3)]
        result = submodular_select(candidates, token_budget=None, max_chunks=3)
        assert len(result) == 3

    def test_token_budget_stops_selection_when_exceeded(self):
        candidates = [{"score": 1.0, "content": "x" * 300} for _ in range(10)]
        result = submodular_select(candidates, token_budget=250, max_chunks=10)
        assert len(result) < 10

    def test_candidate_exceeding_remaining_budget_is_skipped(self):
        candidates = [
            {"score": 1.0, "content": "x" * 100},  # ~33 tokens
            {"score": 0.9, "content": "y" * 10000},  # huge, won't fit
            {"score": 0.5, "content": "z" * 30},  # ~10 tokens, fits
        ]
        result = submodular_select(candidates, token_budget=50, max_chunks=3)
        contents = {c["content"] for c in result}
        assert "y" * 10000 not in contents

    def test_no_candidate_fits_budget_returns_empty(self):
        candidates = [{"score": 1.0, "content": "x" * 10000}]
        result = submodular_select(candidates, token_budget=1, max_chunks=5)
        assert result == []


class TestSubmodularSelectDiversity:
    def test_diversity_penalty_prefers_dissimilar_embedding(self):
        base = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        similar = np.array([0.99, 0.01, 0.0], dtype=np.float32)
        different = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        candidates = [
            {"score": 1.0, "content": "base", "embedding": base},
            {"score": 0.95, "content": "similar", "embedding": similar},
            {"score": 0.9, "content": "different", "embedding": different},
        ]
        result = submodular_select(
            candidates, token_budget=None, max_chunks=2, diversity_lambda=1.0
        )
        contents = [c["content"] for c in result]
        assert "base" in contents
        # With diversity_lambda=1.0, the near-duplicate "similar" should
        # lose to "different" despite its higher raw score.
        assert "different" in contents

    def test_embedding_as_bytes_is_decoded(self):
        emb = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        candidates = [
            {"score": 1.0, "content": "a", "embedding": emb.tobytes()},
            {"score": 0.5, "content": "b", "embedding": emb.tobytes()},
        ]
        result = submodular_select(
            candidates, token_budget=None, max_chunks=2, diversity_lambda=0.5
        )
        assert len(result) == 2

    def test_candidate_without_embedding_has_zero_penalty(self):
        candidates = [
            {"score": 1.0, "content": "a", "embedding": [1.0, 0.0]},
            {"score": 0.9, "content": "b"},  # no embedding key
        ]
        result = submodular_select(
            candidates, token_budget=None, max_chunks=2, diversity_lambda=1.0
        )
        assert len(result) == 2

    def test_custom_field_names(self):
        candidates = [
            {"rank": 0.9, "text": "hello"},
            {"rank": 0.1, "text": "world"},
        ]
        result = submodular_select(
            candidates,
            token_budget=None,
            max_chunks=1,
            score_key="rank",
            content_key="text",
        )
        assert result == [{"rank": 0.9, "text": "hello"}]
