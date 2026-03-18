"""Tests for mcp_server.core.persona_vector — ported from persona-vector.test.js."""

from mcp_server.core.persona_vector import (
    PERSONA_DIMENSIONS,
    build_persona_vector,
    persona_to_array,
    persona_distance,
    persona_drift,
    compose_personas,
    steer_context,
)


def _make_profile(**overrides):
    base = {
        "metacognitive": {
            "activeReflective": 0.3,
            "sensingIntuitive": -0.2,
            "sequentialGlobal": 0.5,
            "problemDecomposition": "top-down",
            "explorationStyle": "depth-first",
            "verificationBehavior": "test-after",
        },
        "sessionShape": {
            "avgDuration": 1200000,
            "avgTurns": 15,
            "avgMessages": 12,
            "burstRatio": 0.4,
            "explorationRatio": 0.3,
            "dominantMode": "mixed",
        },
        "toolPreferences": {
            "Read": {"ratio": 0.8, "avgPerSession": 5},
            "Edit": {"ratio": 0.6, "avgPerSession": 3},
            "Grep": {"ratio": 0.5, "avgPerSession": 2},
            "Bash": {"ratio": 0.3, "avgPerSession": 1},
            "Glob": {"ratio": 0.2, "avgPerSession": 1},
            "Agent": {"ratio": 0.1, "avgPerSession": 0.5},
        },
    }
    base.update(overrides)
    return base


class TestPersonaDimensions:
    def test_has_9_dimensions(self):
        assert len(PERSONA_DIMENSIONS) == 9

    def test_includes_expected_dimensions(self):
        assert "activeReflective" in PERSONA_DIMENSIONS
        assert "thoroughness" in PERSONA_DIMENSIONS
        assert "iterationSpeed" in PERSONA_DIMENSIONS


class TestBuildPersonaVector:
    def test_returns_all_9_numeric_dimensions(self):
        pv = build_persona_vector(_make_profile())
        for dim in PERSONA_DIMENSIONS:
            assert isinstance(pv[dim], (int, float)), f"{dim} should be a number"

    def test_all_dimensions_in_range(self):
        pv = build_persona_vector(_make_profile())
        for dim in PERSONA_DIMENSIONS:
            assert -1 <= pv[dim] <= 1, f"{dim}: {pv[dim]}"

    def test_preserves_cognitive_style(self):
        pv = build_persona_vector(_make_profile())
        assert pv["activeReflective"] == 0.3
        assert pv["sensingIntuitive"] == -0.2
        assert pv["sequentialGlobal"] == 0.5

    def test_handles_empty_profile(self):
        pv = build_persona_vector({})
        for dim in PERSONA_DIMENSIONS:
            assert isinstance(pv[dim], (int, float))
            assert -1 <= pv[dim] <= 1

    def test_burst_heavy_positive_iteration_speed(self):
        pv = build_persona_vector(
            _make_profile(
                sessionShape={
                    "avgDuration": 200000,
                    "avgTurns": 5,
                    "avgMessages": 5,
                    "burstRatio": 0.9,
                    "explorationRatio": 0.1,
                    "dominantMode": "burst",
                },
            )
        )
        assert pv["iterationSpeed"] > 0

    def test_edit_heavy_positive_risk_tolerance(self):
        pv = build_persona_vector(
            _make_profile(
                toolPreferences={
                    "Edit": {"ratio": 0.9, "avgPerSession": 10},
                    "Read": {"ratio": 0.1, "avgPerSession": 1},
                },
            )
        )
        assert pv["riskTolerance"] > 0


class TestPersonaToArray:
    def test_converts_to_9d_array(self):
        pv = build_persona_vector(_make_profile())
        arr = persona_to_array(pv)
        assert len(arr) == 9
        assert arr[0] == pv["activeReflective"]


class TestPersonaDistance:
    def test_zero_for_identical(self):
        pv = build_persona_vector(_make_profile())
        d = persona_distance(pv, pv)
        assert abs(d) < 1e-10

    def test_positive_for_different(self):
        a = build_persona_vector(_make_profile())
        b = build_persona_vector(
            _make_profile(
                metacognitive={
                    "activeReflective": -0.8,
                    "sensingIntuitive": 0.8,
                    "sequentialGlobal": -0.5,
                },
            )
        )
        d = persona_distance(a, b)
        assert d > 0

    def test_in_range_0_to_2(self):
        a = build_persona_vector(_make_profile())
        b = build_persona_vector(
            _make_profile(
                metacognitive={
                    "activeReflective": -1,
                    "sensingIntuitive": 1,
                    "sequentialGlobal": -1,
                },
            )
        )
        d = persona_distance(a, b)
        assert 0 <= d <= 2


class TestPersonaDrift:
    def test_zero_magnitude_for_identical(self):
        pv = build_persona_vector(_make_profile())
        drift = persona_drift(pv, pv)
        assert drift["magnitude"] < 1e-10

    def test_nonzero_magnitude_for_different(self):
        old = build_persona_vector(_make_profile())
        new = build_persona_vector(
            _make_profile(
                metacognitive={
                    "activeReflective": -0.8,
                    "sensingIntuitive": 0.8,
                    "sequentialGlobal": -0.5,
                },
            )
        )
        drift = persona_drift(old, new)
        assert drift["magnitude"] > 0
        assert isinstance(drift["interpretation"], str)
        assert len(drift["interpretation"]) > 0

    def test_direction_contains_all_dims(self):
        old = build_persona_vector(_make_profile())
        new = build_persona_vector(
            _make_profile(
                metacognitive={
                    "activeReflective": -0.5,
                    "sensingIntuitive": 0.5,
                    "sequentialGlobal": 0,
                },
            )
        )
        drift = persona_drift(old, new)
        for dim in PERSONA_DIMENSIONS:
            assert isinstance(drift["direction"][dim], (int, float))


class TestComposePersonas:
    def test_neutral_for_empty(self):
        result = compose_personas([], [])
        for dim in PERSONA_DIMENSIONS:
            assert result[dim] == 0

    def test_same_vector_for_single(self):
        pv = build_persona_vector(_make_profile())
        result = compose_personas([pv], [1])
        for dim in PERSONA_DIMENSIONS:
            assert abs(result[dim] - pv[dim]) < 0.02

    def test_weighted_average(self):
        a = {d: 0 for d in PERSONA_DIMENSIONS}
        a["activeReflective"] = 1
        b = {d: 0 for d in PERSONA_DIMENSIONS}
        b["activeReflective"] = -1
        result = compose_personas([a, b], [1, 1])
        assert result["activeReflective"] == 0

    def test_all_dimensions_in_range(self):
        a = build_persona_vector(_make_profile())
        b = build_persona_vector(
            _make_profile(
                metacognitive={
                    "activeReflective": -1,
                    "sensingIntuitive": 1,
                    "sequentialGlobal": -1,
                },
            )
        )
        result = compose_personas([a, b], [3, 1])
        for dim in PERSONA_DIMENSIONS:
            assert -1 <= result[dim] <= 1, f"{dim}: {result[dim]}"


class TestSteerContext:
    def test_returns_base_when_no_adjustments(self):
        pv = build_persona_vector(_make_profile())
        result = steer_context("Base context.", pv, {})
        assert result == "Base context."

    def test_returns_base_when_null_adjustments(self):
        pv = build_persona_vector(_make_profile())
        result = steer_context("Base context.", pv, None)
        assert result == "Base context."

    def test_appends_steering_when_drift_exceeds_threshold(self):
        pv = build_persona_vector(_make_profile())
        result = steer_context("Base context.", pv, {"thoroughness": 1})
        assert result.startswith("Base context.")
        assert len(result) > len("Base context.")

    def test_no_steer_within_threshold(self):
        pv = {d: 0 for d in PERSONA_DIMENSIONS}
        pv["thoroughness"] = 0.5
        result = steer_context("Base.", pv, {"thoroughness": 0.6})
        assert result == "Base."
