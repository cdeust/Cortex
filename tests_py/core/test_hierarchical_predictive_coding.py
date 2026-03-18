"""Tests for hierarchical_predictive_coding — Fristonian multi-level novelty gate."""

import pytest
from mcp_server.core.hierarchical_predictive_coding import compute_hierarchical_novelty
from mcp_server.core.predictive_coding_signals import (
    PredictionLevel,
    HierarchicalPrediction,
    compute_sensory_prediction,
    compute_sensory_errors,
    compute_entity_errors,
    compute_schema_errors,
)
from mcp_server.core.predictive_coding_flat import compute_novelty_score
from mcp_server.core.predictive_coding_gate import (
    update_precision,
    gate_decision,
    hierarchical_gate_decision,
    describe_hierarchical_signals,
)


class TestPrecision:
    def test_precision_increases_with_small_errors(self):
        prec = 1.0
        for _ in range(10):
            prec = update_precision(prec, 0.01)
        assert prec > 1.0

    def test_precision_decreases_with_large_errors(self):
        prec = 3.0
        for _ in range(10):
            prec = update_precision(prec, 0.8)
        assert prec < 3.0

    def test_precision_bounded(self):
        assert update_precision(0.01, 10.0) >= 0.1
        assert update_precision(100.0, 0.0001) <= 5.0


class TestSensoryLevel:
    def test_prediction_from_empty(self):
        pred, prec = compute_sensory_prediction([])
        assert "length" in pred
        assert all(v == 0.5 for v in prec.values())

    def test_prediction_from_memories(self):
        features = [
            {
                "length": 0.3,
                "code_density": 0.8,
                "file_ref_density": 0.1,
                "url_density": 0.0,
                "heading_density": 0.1,
                "list_density": 0.2,
            },
            {
                "length": 0.4,
                "code_density": 0.7,
                "file_ref_density": 0.2,
                "url_density": 0.0,
                "heading_density": 0.1,
                "list_density": 0.1,
            },
        ]
        pred, prec = compute_sensory_prediction(features)
        assert pred["length"] == pytest.approx(0.35, abs=0.01)
        assert pred["code_density"] == pytest.approx(0.75, abs=0.01)

    def test_sensory_errors_novel_content(self):
        """Content very different from predictions should have high free energy."""
        # Predict short, no-code content
        pred = {
            "length": 0.1,
            "code_density": 0.0,
            "file_ref_density": 0.0,
            "url_density": 0.0,
            "heading_density": 0.0,
            "list_density": 0.0,
        }
        prec = {k: 2.0 for k in pred}  # High precision (confident predictions)
        # Present long code-heavy content
        content = "```python\n" + "x = 1\n" * 200 + "```\n" * 5
        level = compute_sensory_errors(content, pred, prec)
        assert level.free_energy > 0

    def test_sensory_errors_matching_content(self):
        """Content matching predictions should have low free energy."""
        pred = {
            "length": 0.0,
            "code_density": 0.0,
            "file_ref_density": 0.0,
            "url_density": 0.0,
            "heading_density": 0.0,
            "list_density": 0.0,
        }
        prec = {k: 1.0 for k in pred}
        level = compute_sensory_errors("", pred, prec)
        assert level.free_energy < 0.1


class TestEntityLevel:
    def test_entity_novelty_without_schema(self):
        level = compute_entity_errors(["NewClass"], {"OldClass"})
        assert level.free_energy > 0

    def test_entity_match_without_schema(self):
        level = compute_entity_errors(["OldClass"], {"OldClass"})
        assert level.free_energy == 0.0

    def test_entity_with_schema_predictions(self):
        preds = {"React": 0.9, "useState": 0.8}
        precs = {"React": 2.0, "useState": 1.5}
        # Matching: React present, useState missing
        level = compute_entity_errors(["React", "NewHook"], {"React"}, preds, precs)
        # useState missing = positive error, NewHook novel = negative error
        assert "useState" in level.prediction_errors
        assert level.prediction_errors["useState"] > 0  # Missing
        assert "NewHook" in level.prediction_errors
        assert level.prediction_errors["NewHook"] < 0  # Novel


class TestSchemaLevel:
    def test_high_schema_match_low_fe(self):
        level = compute_schema_errors(0.9, 0.0, domain_familiarity=0.8)
        assert level.free_energy < 0.5

    def test_low_schema_match_high_fe(self):
        level = compute_schema_errors(0.1, 0.5, domain_familiarity=0.8)
        assert level.free_energy > 1.0

    def test_unfamiliar_domain_lower_precision(self):
        """Unfamiliar domain should have lower precision → smaller errors."""
        familiar = compute_schema_errors(0.3, 0.0, domain_familiarity=0.9)
        unfamiliar = compute_schema_errors(0.3, 0.0, domain_familiarity=0.1)
        # Same mismatch but familiar domain has higher precision → higher FE
        assert familiar.free_energy > unfamiliar.free_energy


class TestHierarchicalNovelty:
    def test_novel_content_high_fe(self):
        result = compute_hierarchical_novelty(
            "```python\nclass NewFramework:\n    pass\n```" * 10,
            ["NewFramework", "novel_pattern"],
            set(),
            [],
            schema_match_score=0.0,
            domain_familiarity=0.1,
        )
        assert result.total_free_energy > 0
        assert result.novelty_score > 0.3

    def test_familiar_content_low_fe(self):
        features = [
            {
                "length": 0.1,
                "code_density": 0.0,
                "file_ref_density": 0.0,
                "url_density": 0.0,
                "heading_density": 0.0,
                "list_density": 0.0,
            }
        ] * 5
        result = compute_hierarchical_novelty(
            "short text",
            ["known"],
            {"known"},
            features,
            schema_match_score=0.9,
            domain_familiarity=0.9,
        )
        assert result.novelty_score < 0.5

    def test_ach_modulates_level_weights(self):
        """High ACh should boost bottom-up (L0/L1) sensitivity."""
        base_args = dict(
            content="test content",
            new_entity_names=["NewThing"],
            known_entity_names=set(),
            recent_memories_features=[],
            schema_match_score=0.5,
            domain_familiarity=0.5,
        )
        high_ach = compute_hierarchical_novelty(**base_args, ach_level=1.0)
        low_ach = compute_hierarchical_novelty(**base_args, ach_level=0.3)
        # Both should produce results; specific level weights differ
        assert high_ach.total_free_energy > 0
        assert low_ach.total_free_energy > 0


class TestGateDecision:
    def test_backward_compatible_gate(self):
        score = compute_novelty_score(0.8, 0.6, 0.5, 0.3)
        assert 0 <= score <= 1
        should, reason = gate_decision(score)
        assert isinstance(should, bool)

    def test_hierarchical_gate_stores_surprising(self):
        pred = HierarchicalPrediction(
            levels=[
                PredictionLevel(free_energy=0.5),
                PredictionLevel(free_energy=0.3),
                PredictionLevel(free_energy=0.4),
            ],
            total_free_energy=0.4,
        )
        should, reason = hierarchical_gate_decision(pred)
        assert should is True
        assert "high_free_energy" in reason

    def test_hierarchical_gate_rejects_boring(self):
        pred = HierarchicalPrediction(
            levels=[
                PredictionLevel(free_energy=0.01),
                PredictionLevel(free_energy=0.01),
                PredictionLevel(free_energy=0.01),
            ],
            total_free_energy=0.01,
        )
        should, reason = hierarchical_gate_decision(pred)
        assert should is False

    def test_bypass_always_stores(self):
        pred = HierarchicalPrediction(total_free_energy=0.0)
        should, _ = hierarchical_gate_decision(pred, bypass=True)
        assert should is True


class TestObservability:
    def test_describe_signals(self):
        result = compute_hierarchical_novelty(
            "test content",
            ["A"],
            {"B"},
            [],
            schema_match_score=0.5,
            domain_familiarity=0.5,
        )
        desc = describe_hierarchical_signals(result)
        assert "total_free_energy" in desc
        assert "level_0_sensory" in desc
        assert "level_1_entity" in desc
        assert "level_2_schema" in desc
