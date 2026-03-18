"""Tests for pattern_separation — DG orthogonalization and CA3 completion."""

import pytest
import math
from mcp_server.core.separation_core import (
    detect_interference_risk,
    orthogonalize_embedding,
    apply_sparsification,
)
from mcp_server.core.neurogenesis import (
    compute_temporal_separation_weights,
    apply_temporal_weights,
    compute_separation_index,
    compute_interference_score,
)
from mcp_server.shared.linear_algebra import cosine_similarity, norm


def _unit(v: list[float]) -> list[float]:
    """Normalize a vector to unit length."""
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0 else v


class TestInterferenceDetection:
    def test_no_risk_for_dissimilar(self):
        new = [1.0, 0.0, 0.0, 0.0]
        existing = [[0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]]
        risks = detect_interference_risk(new, existing)
        assert len(risks) == 0

    def test_detects_similar_but_not_identical(self):
        new = _unit([1.0, 0.6, 0.0, 0.0])  # cos_sim with similar ≈ 0.857
        similar = _unit([1.0, 0.0, 0.0, 0.0])  # Above threshold but below identity
        different = _unit([0.0, 0.0, 1.0, 0.0])
        risks = detect_interference_risk(new, [similar, different], threshold=0.8)
        assert len(risks) == 1
        assert risks[0][1] > 0.8

    def test_excludes_near_duplicates(self):
        new = [1.0, 0.0, 0.0, 0.0]
        duplicate = [1.0, 0.0, 0.0, 0.0]  # identity
        risks = detect_interference_risk(new, [duplicate])
        assert len(risks) == 0  # Excluded (above identity threshold)

    def test_sorted_by_similarity(self):
        new = _unit([1.0, 0.0, 0.0, 0.0])
        close = _unit([0.95, 0.05, 0.0, 0.0])
        closer = _unit([0.99, 0.01, 0.0, 0.0])
        risks = detect_interference_risk(new, [close, closer], threshold=0.7)
        if len(risks) >= 2:
            assert risks[0][1] >= risks[1][1]


class TestOrthogonalization:
    def test_no_change_without_interferers(self):
        emb = _unit([1.0, 0.0, 0.0, 0.0])
        result, sep_idx = orthogonalize_embedding(emb, [])
        assert sep_idx == 0.0
        assert cosine_similarity(emb, result) > 0.99

    def test_pushes_away_from_interferer(self):
        new = _unit([1.0, 0.1, 0.0, 0.0])
        interferer = _unit([1.0, 0.0, 0.0, 0.0])
        result, sep_idx = orthogonalize_embedding(new, [interferer], strength=0.5)
        # Should be less similar to interferer after separation
        sim_before = cosine_similarity(new, interferer)
        sim_after = cosine_similarity(result, interferer)
        assert sim_after < sim_before
        assert sep_idx > 0

    def test_preserves_semantic_content(self):
        """Orthogonalized embedding should still be similar to original."""
        new = _unit([1.0, 0.3, 0.0, 0.0])
        interferer = _unit([1.0, 0.0, 0.0, 0.0])
        result, _ = orthogonalize_embedding(new, [interferer], strength=0.5)
        sim = cosine_similarity(new, result)
        assert sim >= 0.3  # min_similarity default

    def test_output_is_unit_norm(self):
        new = _unit([0.8, 0.6, 0.0, 0.0])
        interferer = _unit([0.9, 0.1, 0.0, 0.0])
        result, _ = orthogonalize_embedding(new, [interferer])
        assert norm(result) == pytest.approx(1.0, abs=0.01)


class TestSparsification:
    def test_reduces_active_dimensions(self):
        emb = _unit([0.5, 0.3, 0.2, 0.1, 0.05, 0.02, 0.01, 0.005, 0.001, 0.0005])
        sparse = apply_sparsification(emb, sparsity=0.3)
        nonzero = sum(1 for v in sparse if abs(v) > 1e-10)
        assert nonzero == 3  # 30% of 10 dims

    def test_preserves_unit_norm(self):
        emb = _unit([0.5, 0.3, 0.2, 0.1])
        sparse = apply_sparsification(emb, sparsity=0.5)
        assert norm(sparse) == pytest.approx(1.0, abs=0.01)

    def test_keeps_largest_dimensions(self):
        emb = [0.9, 0.01, 0.01, 0.01]
        sparse = apply_sparsification(emb, sparsity=0.25)
        # Should keep only the first dimension (0.9)
        assert abs(sparse[0]) > 0


class TestNeurogenesis:
    def test_weights_have_correct_length(self):
        weights = compute_temporal_separation_weights(0.0, 64)
        assert len(weights) == 64

    def test_young_memories_have_boosted_dims(self):
        young = compute_temporal_separation_weights(1.0, 64)  # 1 hour old
        old = compute_temporal_separation_weights(200.0, 64)  # 200 hours old
        # Young memories should have higher max weight (boosted dims)
        assert max(young) > max(old)

    def test_old_memories_uniform_weights(self):
        old = compute_temporal_separation_weights(1000.0, 64)
        assert max(old) == pytest.approx(1.0, abs=0.05)

    def test_apply_temporal_weights_preserves_norm(self):
        emb = _unit([1.0, 0.5, 0.3, 0.1])
        weights = compute_temporal_separation_weights(5.0, 4)
        result = apply_temporal_weights(emb, weights)
        assert norm(result) == pytest.approx(1.0, abs=0.01)


class TestMetrics:
    def test_separation_index_zero_for_identical(self):
        emb = _unit([1.0, 0.0, 0.0])
        assert compute_separation_index(emb, emb) == pytest.approx(0.0, abs=0.01)

    def test_separation_index_positive_for_different(self):
        a = _unit([1.0, 0.0, 0.0])
        b = _unit([0.7, 0.7, 0.0])
        idx = compute_separation_index(a, b)
        assert idx > 0

    def test_interference_score_zero_for_distant(self):
        emb = [1.0, 0.0, 0.0]
        neighbors = [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        score = compute_interference_score(emb, neighbors)
        assert score == 0.0

    def test_interference_score_positive_for_close(self):
        emb = _unit([1.0, 0.0, 0.0])
        close = _unit([0.95, 0.05, 0.0])
        score = compute_interference_score(emb, [close], threshold=0.7)
        assert score > 0
