"""Tests for mcp_server.core.context_generator — ported from context-generator.test.js."""

from mcp_server.core.context_generator import generate_context, generate_short_context


def _make_profile(**overrides):
    base = {
        "label": "Jarvis",
        "entryPoints": [
            {"pattern": "fix / api / auth", "frequency": 5, "confidence": 0.8}
        ],
        "recurringPatterns": [
            {"pattern": "read before edit", "frequency": 4, "confidence": 0.6},
            {"pattern": "grep then fix", "frequency": 3, "confidence": 0.5},
        ],
        "blindSpots": [
            {
                "type": "category",
                "value": "testing",
                "severity": "high",
                "description": "No testing sessions",
                "suggestion": "Add tests",
            },
        ],
        "connectionBridges": [
            {"toDomain": "devops", "pattern": "deployment pipeline", "weight": 2},
        ],
        "metacognitive": {
            "explorationStyle": "depth-first",
            "problemDecomposition": "top-down",
            "activeReflective": 0.3,
            "sensingIntuitive": -0.2,
            "sequentialGlobal": 0.1,
            "verificationBehavior": "test-after",
        },
        "sessionShape": {
            "dominantMode": "burst",
            "avgDuration": 300000,
            "avgTurns": 8,
            "burstRatio": 0.7,
        },
        "sessionCount": 25,
        "confidence": 0.72,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# generate_context
# ---------------------------------------------------------------------------


class TestGenerateContext:
    def test_includes_all_sections(self):
        ctx = generate_context("jarvis", _make_profile())
        assert "You're working in Jarvis" in ctx
        assert "You typically fix / api / auth" in ctx
        assert "read before edit" in ctx
        assert "grep then fix" in ctx
        assert "Blind spot: No testing sessions" in ctx
        assert "Add tests" in ctx
        assert "connect this to devops" in ctx
        assert "depth-first" in ctx
        assert "top-down" in ctx
        assert "burst" in ctx
        assert "25 prior sessions" in ctx
        assert "72% confidence" in ctx

    def test_null_profile(self):
        assert (
            generate_context("jarvis", None)
            == "No cognitive profile yet. Building one as we go."
        )

    def test_null_domain(self):
        assert (
            generate_context(None, _make_profile())
            == "No cognitive profile yet. Building one as we go."
        )

    def test_missing_label_uses_domain_id(self):
        ctx = generate_context("jarvis", _make_profile(label=None))
        assert "You're working in jarvis" in ctx

    def test_no_entry_points(self):
        ctx = generate_context("d", _make_profile(entryPoints=[]))
        assert "You typically" not in ctx

    def test_single_recurring_pattern(self):
        ctx = generate_context(
            "d",
            _make_profile(
                recurringPatterns=[
                    {"pattern": "read first", "frequency": 4, "confidence": 0.6}
                ]
            ),
        )
        assert "You read first." in ctx
        assert ", and you" not in ctx

    def test_no_blind_spots(self):
        ctx = generate_context("d", _make_profile(blindSpots=[]))
        assert "Blind spot" not in ctx

    def test_no_bridges(self):
        ctx = generate_context("d", _make_profile(connectionBridges=[]))
        assert "connect this to" not in ctx

    def test_no_metacognitive(self):
        ctx = generate_context("d", _make_profile(metacognitive=None))
        assert "thinker" not in ctx

    def test_no_session_shape(self):
        ctx = generate_context("d", _make_profile(sessionShape=None))
        assert "prefer" not in ctx

    def test_zero_session_count_and_confidence(self):
        ctx = generate_context("d", _make_profile(sessionCount=0, confidence=0))
        assert "0 prior sessions" in ctx
        assert "0% confidence" in ctx

    def test_blind_spot_without_suggestion(self):
        ctx = generate_context(
            "d",
            _make_profile(
                blindSpots=[
                    {
                        "type": "category",
                        "value": "x",
                        "severity": "high",
                        "description": "Missing X",
                    }
                ]
            ),
        )
        assert "Blind spot: Missing X" in ctx

    # --- New tests covering lines 67-74 (featureActivations) ---

    def test_includes_dominant_behavioral_feature(self):
        ctx = generate_context(
            "d",
            _make_profile(featureActivations={"deep-diver": 0.9, "scanner": 0.3}),
        )
        assert "dominant behavioral mode is deep-diver" in ctx

    def test_feature_activations_with_negative_weights(self):
        ctx = generate_context(
            "d",
            _make_profile(featureActivations={"cautious": -0.8, "bold": 0.2}),
        )
        # abs(-0.8) > abs(0.2) so "cautious" should be dominant
        assert "dominant behavioral mode is cautious" in ctx

    def test_feature_activations_empty_dict(self):
        ctx = generate_context("d", _make_profile(featureActivations={}))
        assert "dominant behavioral mode" not in ctx

    def test_feature_activations_none(self):
        ctx = generate_context("d", _make_profile(featureActivations=None))
        assert "dominant behavioral mode" not in ctx

    def test_feature_activations_single_entry(self):
        ctx = generate_context(
            "d",
            _make_profile(featureActivations={"explorer": 0.5}),
        )
        assert "dominant behavioral mode is explorer" in ctx

    def test_no_recurring_patterns(self):
        ctx = generate_context("d", _make_profile(recurringPatterns=[]))
        assert "You read before edit" not in ctx
        assert ", and you" not in ctx

    def test_metacognitive_only_exploration_style(self):
        ctx = generate_context(
            "d",
            _make_profile(metacognitive={"explorationStyle": "breadth-first"}),
        )
        assert "breadth-first" in ctx
        assert "thinker" in ctx

    def test_metacognitive_only_problem_decomposition(self):
        ctx = generate_context(
            "d",
            _make_profile(metacognitive={"problemDecomposition": "bottom-up"}),
        )
        assert "bottom-up" in ctx
        assert "thinker" in ctx

    def test_session_shape_without_dominant_mode(self):
        ctx = generate_context(
            "d",
            _make_profile(sessionShape={"avgDuration": 300000}),
        )
        assert "prefer" not in ctx

    def test_none_session_count_and_confidence(self):
        ctx = generate_context("d", _make_profile(sessionCount=None, confidence=None))
        assert "0 prior sessions" in ctx
        assert "0% confidence" in ctx


# ---------------------------------------------------------------------------
# generate_short_context
# ---------------------------------------------------------------------------


class TestGenerateShortContext:
    def test_full_format(self):
        short = generate_short_context("jarvis", _make_profile())
        assert short == "Jarvis · depth-first · top-down · burst"

    def test_null_profile(self):
        assert generate_short_context("d", None) is None

    def test_null_domain(self):
        assert generate_short_context(None, _make_profile()) is None

    def test_missing_label_uses_domain_id(self):
        short = generate_short_context("mydom", _make_profile(label=None))
        assert short.startswith("mydom")

    def test_no_metacognitive(self):
        short = generate_short_context("d", _make_profile(metacognitive=None))
        assert "depth-first" not in short

    def test_no_session_shape(self):
        short = generate_short_context("d", _make_profile(sessionShape=None))
        assert "burst" not in short

    def test_label_only(self):
        short = generate_short_context(
            "d", _make_profile(metacognitive=None, sessionShape=None)
        )
        assert short == "Jarvis"

    def test_metacognitive_only_exploration(self):
        short = generate_short_context(
            "d",
            _make_profile(
                metacognitive={"explorationStyle": "breadth-first"}, sessionShape=None
            ),
        )
        assert "breadth-first" in short
        assert "top-down" not in short

    def test_session_shape_without_dominant_mode(self):
        short = generate_short_context(
            "d",
            _make_profile(metacognitive=None, sessionShape={"avgDuration": 300000}),
        )
        assert short == "Jarvis"
