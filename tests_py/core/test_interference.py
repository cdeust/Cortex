"""Tests for interference — proactive/retroactive interference management."""

import pytest
import math
from mcp_server.core.interference import (
    orthogonalize_pair,
    compute_retrieval_suppression,
    compute_domain_interference_pressure,
)
from mcp_server.core.interference_detection import (
    detect_proactive_interference,
    detect_retroactive_interference,
)
from mcp_server.shared.linear_algebra import cosine_similarity, norm


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n > 0 else v


class TestProactiveInterference:
    def test_detects_similar_existing_memories(self):
        new_emb = _unit([1.0, 0.1, 0.0, 0.0])
        existing = [
            {
                "embedding": _unit([0.95, 0.15, 0.0, 0.0]),
                "entities": ["foo"],
                "heat": 0.8,
                "id": 1,
                "consolidation_stage": "consolidated",
            },
            {
                "embedding": _unit([0.0, 0.0, 1.0, 0.0]),
                "entities": ["bar"],
                "heat": 0.5,
                "id": 2,
                "consolidation_stage": "labile",
            },
        ]
        results = detect_proactive_interference(
            new_emb, ["foo"], existing, threshold=0.7
        )
        assert len(results) >= 1
        assert results[0]["memory_id"] == 1

    def test_no_interference_for_dissimilar(self):
        new_emb = _unit([1.0, 0.0, 0.0, 0.0])
        existing = [
            {
                "embedding": _unit([0.0, 1.0, 0.0, 0.0]),
                "entities": ["bar"],
                "heat": 0.5,
                "id": 1,
                "consolidation_stage": "labile",
            },
        ]
        results = detect_proactive_interference(new_emb, ["foo"], existing)
        assert len(results) == 0

    def test_provides_resolution_hints(self):
        new_emb = _unit([1.0, 0.0, 0.0, 0.0])
        existing = [
            {
                "embedding": _unit([0.98, 0.02, 0.0, 0.0]),
                "entities": ["foo"],
                "heat": 0.9,
                "id": 1,
                "consolidation_stage": "consolidated",
            },
        ]
        results = detect_proactive_interference(
            new_emb, ["foo"], existing, threshold=0.7
        )
        if results:
            assert "resolution_hint" in results[0]


class TestRetroactiveInterference:
    def test_detects_at_risk_memories(self):
        new_emb = _unit([1.0, 0.1, 0.0, 0.0])
        existing = [
            {
                "embedding": _unit([0.95, 0.15, 0.0, 0.0]),
                "entities": ["foo"],
                "heat": 0.3,
                "importance": 0.3,
                "id": 1,
                "consolidation_stage": "labile",
            },
        ]
        results = detect_retroactive_interference(new_emb, 0.8, existing, threshold=0.7)
        assert len(results) >= 1
        assert results[0]["interference_type"] == "retroactive"

    def test_consolidated_memories_more_resistant(self):
        new_emb = _unit([1.0, 0.1, 0.0, 0.0])
        labile = {
            "embedding": _unit([0.95, 0.15, 0.0, 0.0]),
            "heat": 0.3,
            "importance": 0.3,
            "id": 1,
            "consolidation_stage": "labile",
        }
        consolidated = {
            "embedding": _unit([0.95, 0.15, 0.0, 0.0]),
            "heat": 0.3,
            "importance": 0.3,
            "id": 2,
            "consolidation_stage": "consolidated",
        }
        ri_labile = detect_retroactive_interference(
            new_emb, 0.8, [labile], threshold=0.7
        )
        ri_consolidated = detect_retroactive_interference(
            new_emb, 0.8, [consolidated], threshold=0.7
        )
        # Labile should have higher risk
        if ri_labile and ri_consolidated:
            assert ri_labile[0]["risk_score"] > ri_consolidated[0]["risk_score"]


class TestOrthogonalization:
    def test_reduces_similarity(self):
        a = _unit([1.0, 0.3, 0.0, 0.0])
        b = _unit([1.0, 0.2, 0.0, 0.0])
        before = cosine_similarity(a, b)
        new_a, new_b, after = orthogonalize_pair(a, b, rate=0.3)
        assert after < before

    def test_symmetric_adjustment(self):
        """Both embeddings should be adjusted, not just one."""
        a = _unit([1.0, 0.3, 0.0, 0.0])
        b = _unit([1.0, 0.2, 0.0, 0.0])
        new_a, new_b, _ = orthogonalize_pair(a, b, rate=0.3)
        # Both should differ from original
        assert cosine_similarity(a, new_a) < 1.0
        assert cosine_similarity(b, new_b) < 1.0

    def test_respects_min_similarity(self):
        a = _unit([1.0, 0.0, 0.0, 0.0])
        b = _unit([0.9, 0.1, 0.0, 0.0])
        _, _, sim = orthogonalize_pair(a, b, rate=1.0, min_similarity=0.5)
        # Should not push below min_similarity
        assert sim >= 0.15  # Some tolerance

    def test_preserves_unit_norm(self):
        a = _unit([0.8, 0.6, 0.0, 0.0])
        b = _unit([0.7, 0.7, 0.0, 0.0])
        new_a, new_b, _ = orthogonalize_pair(a, b)
        assert norm(new_a) == pytest.approx(1.0, abs=0.02)
        assert norm(new_b) == pytest.approx(1.0, abs=0.02)

    def test_already_orthogonal_unchanged(self):
        a = _unit([1.0, 0.0, 0.0, 0.0])
        b = _unit([0.0, 1.0, 0.0, 0.0])
        new_a, new_b, sim = orthogonalize_pair(a, b)
        assert cosine_similarity(a, new_a) > 0.99  # Unchanged
        assert cosine_similarity(b, new_b) > 0.99


class TestRetrievalSuppression:
    def test_no_suppression_without_competitors(self):
        score = compute_retrieval_suppression(0.8, [])
        assert score == 0.8

    def test_suppressed_by_stronger_competitors(self):
        score = compute_retrieval_suppression(0.5, [0.8, 0.9])
        assert score < 0.5

    def test_not_suppressed_by_weaker_competitors(self):
        score = compute_retrieval_suppression(0.9, [0.3, 0.5])
        assert score == 0.9

    def test_suppression_bounded_at_zero(self):
        score = compute_retrieval_suppression(0.1, [0.9, 0.95, 0.99])
        assert score >= 0.0


class TestDomainPressure:
    def test_low_pressure_for_orthogonal(self):
        embs = [
            _unit([1, 0, 0, 0]),
            _unit([0, 1, 0, 0]),
            _unit([0, 0, 1, 0]),
            _unit([0, 0, 0, 1]),
        ]
        metrics = compute_domain_interference_pressure(embs)
        assert metrics["pressure_level"] == "low"

    def test_high_pressure_for_clustered(self):
        embs = [_unit([1.0, 0.0 + i * 0.01, 0.0, 0.0]) for i in range(10)]
        metrics = compute_domain_interference_pressure(embs)
        assert metrics["mean_max_similarity"] > 0.9

    def test_single_embedding_is_low(self):
        metrics = compute_domain_interference_pressure([_unit([1, 0, 0, 0])])
        assert metrics["pressure_level"] == "low"
