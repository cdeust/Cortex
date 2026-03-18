"""Tests for ablation — lesion study framework."""

import pytest
from mcp_server.core.ablation import (
    Mechanism,
    AblationConfig,
    compute_ablation_deltas,
    compute_impact_score,
    generate_interpretation,
    create_ablation_result,
    neutral_encoding_strength,
    neutral_schema_match,
)
from mcp_server.core.ablation_report import (
    plan_full_ablation_study,
    format_ablation_report,
)


class TestAblationConfig:
    def test_all_enabled_by_default(self):
        config = AblationConfig()
        for m in Mechanism:
            assert config.is_enabled(m)

    def test_disable_one(self):
        config = AblationConfig().disable(Mechanism.OSCILLATORY_CLOCK)
        assert not config.is_enabled(Mechanism.OSCILLATORY_CLOCK)
        assert config.is_enabled(Mechanism.SCHEMA_ENGINE)

    def test_enable_after_disable(self):
        config = (
            AblationConfig()
            .disable(Mechanism.SCHEMA_ENGINE)
            .enable(Mechanism.SCHEMA_ENGINE)
        )
        assert config.is_enabled(Mechanism.SCHEMA_ENGINE)

    def test_disable_all_except(self):
        config = AblationConfig().disable_all_except(Mechanism.OSCILLATORY_CLOCK)
        assert config.is_enabled(Mechanism.OSCILLATORY_CLOCK)
        assert not config.is_enabled(Mechanism.SCHEMA_ENGINE)

    def test_string_key_works(self):
        config = AblationConfig().disable("oscillatory_clock")
        assert not config.is_enabled("oscillatory_clock")


class TestDeltas:
    def test_compute_deltas(self):
        baseline = {"heat": 0.5, "precision": 0.8}
        ablation = {"heat": 0.3, "precision": 0.9}
        deltas = compute_ablation_deltas(baseline, ablation)
        assert deltas["heat"] == pytest.approx(-0.2)
        assert deltas["precision"] == pytest.approx(0.1)

    def test_missing_keys(self):
        deltas = compute_ablation_deltas({"a": 1.0}, {"b": 2.0})
        assert "a" in deltas and "b" in deltas


class TestImpactScore:
    def test_zero_impact_no_change(self):
        assert compute_impact_score({"a": 0.0, "b": 0.0}) == pytest.approx(
            0.5, abs=0.01
        )

    def test_high_impact_large_deltas(self):
        score = compute_impact_score({"a": 0.5, "b": -0.3})
        assert score > 0.5

    def test_empty_deltas(self):
        assert compute_impact_score({}) == 0.0


class TestInterpretation:
    def test_minimal_impact(self):
        interp = generate_interpretation("test_mechanism", {}, 0.05)
        assert "minimal" in interp.lower()

    def test_critical_impact(self):
        interp = generate_interpretation("test_mechanism", {"heat": -0.4}, 0.7)
        assert "CRITICAL" in interp

    def test_moderate_impact(self):
        interp = generate_interpretation("test_mechanism", {"heat": -0.1}, 0.35)
        assert "meaningfully" in interp.lower()


class TestAblationResult:
    def test_create_result(self):
        result = create_ablation_result(
            "oscillatory_clock",
            {"avg_heat": 0.5, "survival": 0.8},
            {"avg_heat": 0.4, "survival": 0.6},
        )
        assert result.mechanism == "oscillatory_clock"
        assert result.impact_score > 0
        assert len(result.interpretation) > 0


class TestStudyPlanning:
    def test_full_study_has_all_mechanisms(self):
        study = plan_full_ablation_study()
        assert len(study) == len(Mechanism)

    def test_exclude_mechanisms(self):
        study = plan_full_ablation_study(exclude={"oscillatory_clock"})
        assert "oscillatory_clock" not in study


class TestReportFormatting:
    def test_format_report(self):
        results = [
            create_ablation_result("mech_a", {"heat": 0.5}, {"heat": 0.2}),
            create_ablation_result("mech_b", {"heat": 0.5}, {"heat": 0.49}),
        ]
        report = format_ablation_report(results)
        assert "Ablation Study Report" in report
        assert "mech_a" in report
        assert "Summary" in report


class TestNeutralValues:
    def test_neutral_values(self):
        assert neutral_encoding_strength() == 1.0
        assert neutral_schema_match() == 0.0
