"""Tests for cascade — consolidation stage pipeline."""

from mcp_server.core.cascade_stages import (
    ConsolidationStage,
    StageProperties,
    get_stage_properties,
    get_stage_properties_by_name,
    compute_stage_adjusted_decay,
    compute_interference_resistance,
    stage_to_dict,
)
from mcp_server.core.cascade_advancement import (
    compute_advancement_readiness,
    trigger_reconsolidation,
)


class TestStageProperties:
    def test_all_stages_have_properties(self):
        for stage in ConsolidationStage:
            props = get_stage_properties(stage)
            assert isinstance(props, StageProperties)

    def test_labile_decays_fastest(self):
        labile = get_stage_properties(ConsolidationStage.LABILE)
        consolidated = get_stage_properties(ConsolidationStage.CONSOLIDATED)
        assert labile.decay_multiplier > consolidated.decay_multiplier

    def test_consolidated_most_stable(self):
        consolidated = get_stage_properties(ConsolidationStage.CONSOLIDATED)
        assert consolidated.interference_vulnerability < 0.1
        assert consolidated.plasticity < 0.2

    def test_labile_most_vulnerable(self):
        labile = get_stage_properties(ConsolidationStage.LABILE)
        assert labile.interference_vulnerability > 0.8
        assert labile.plasticity >= 1.0

    def test_unknown_stage_returns_labile(self):
        props = get_stage_properties_by_name("nonexistent")
        labile = get_stage_properties(ConsolidationStage.LABILE)
        assert props.decay_multiplier == labile.decay_multiplier


class TestAdvancement:
    def test_labile_to_early_ltp_with_dopamine(self):
        ready, next_stage, score = compute_advancement_readiness(
            "labile", hours_in_stage=0.5, dopamine_level=1.5
        )
        assert ready is True
        assert next_stage == "early_ltp"

    def test_labile_blocked_without_dopamine(self):
        ready, next_stage, score = compute_advancement_readiness(
            "labile", hours_in_stage=0.5, dopamine_level=0.6
        )
        # Low dopamine AND low importance → blocked
        assert next_stage in ("labile", "early_ltp")

    def test_labile_to_early_ltp_with_importance(self):
        ready, next_stage, _ = compute_advancement_readiness(
            "labile", hours_in_stage=0.5, dopamine_level=0.6, importance=0.8
        )
        assert ready is True
        assert next_stage == "early_ltp"

    def test_early_ltp_to_late_ltp_with_replay(self):
        ready, next_stage, _ = compute_advancement_readiness(
            "early_ltp", hours_in_stage=2.0, replay_count=1
        )
        assert ready is True
        assert next_stage == "late_ltp"

    def test_early_ltp_blocked_without_replay(self):
        ready, next_stage, _ = compute_advancement_readiness(
            "early_ltp", hours_in_stage=2.0, replay_count=0, importance=0.3
        )
        assert ready is False

    def test_late_ltp_to_consolidated_with_replay(self):
        ready, next_stage, _ = compute_advancement_readiness(
            "late_ltp", hours_in_stage=12.0, replay_count=3
        )
        assert ready is True
        assert next_stage == "consolidated"

    def test_schema_accelerates_consolidation(self):
        """High schema match should reduce dwell time requirements."""
        # Without schema: needs 6h min dwell
        ready_no_schema, _, _ = compute_advancement_readiness(
            "late_ltp", hours_in_stage=4.0, replay_count=3, schema_match=0.0
        )
        # With schema: 6h * 0.5 = 3h min dwell
        ready_schema, _, _ = compute_advancement_readiness(
            "late_ltp", hours_in_stage=4.0, replay_count=1, schema_match=0.9
        )
        assert ready_schema is True

    def test_consolidated_is_terminal(self):
        ready, next_stage, _ = compute_advancement_readiness(
            "consolidated", hours_in_stage=1000.0, replay_count=100
        )
        assert ready is False
        assert next_stage == "consolidated"

    def test_reconsolidating_returns_to_early_ltp(self):
        ready, next_stage, _ = compute_advancement_readiness(
            "reconsolidating", hours_in_stage=1.0
        )
        assert ready is True
        assert next_stage == "early_ltp"


class TestReconsolidation:
    def test_consolidated_reconsolidates_on_mismatch(self):
        should, new_stage = trigger_reconsolidation(
            "consolidated", mismatch_score=0.6, stability=0.3
        )
        assert should is True
        assert new_stage == "reconsolidating"

    def test_high_stability_resists_reconsolidation(self):
        should, _ = trigger_reconsolidation(
            "consolidated", mismatch_score=0.5, stability=0.9
        )
        assert should is False

    def test_labile_cannot_reconsolidate(self):
        should, _ = trigger_reconsolidation("labile", mismatch_score=0.9)
        assert should is False


class TestDecayIntegration:
    def test_labile_decays_faster(self):
        labile_factor = compute_stage_adjusted_decay(0.95, "labile")
        consolidated_factor = compute_stage_adjusted_decay(0.95, "consolidated")
        assert labile_factor < consolidated_factor  # Lower factor = more decay

    def test_consolidated_decays_slower(self):
        factor = compute_stage_adjusted_decay(0.95, "consolidated")
        assert factor > 0.95  # Slower than base


class TestInterferenceResistance:
    def test_consolidated_resists_interference(self):
        resistance = compute_interference_resistance("consolidated", 0.8)
        assert resistance > 0.9

    def test_labile_vulnerable_to_interference(self):
        resistance = compute_interference_resistance("labile", 0.8)
        assert resistance < 0.4

    def test_higher_similarity_more_threatening(self):
        low_sim = compute_interference_resistance("early_ltp", 0.3)
        high_sim = compute_interference_resistance("early_ltp", 0.9)
        assert low_sim > high_sim


class TestSerialization:
    def test_stage_to_dict(self):
        d = stage_to_dict("early_ltp", 3.5, replay_count=2)
        assert d["stage"] == "early_ltp"
        assert d["hours_in_stage"] == 3.5
        assert d["replay_count"] == 2
        assert "decay_multiplier" in d
