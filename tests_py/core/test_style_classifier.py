"""Tests for mcp_server.core.style_classifier — ported from style-classifier.test.js."""

from mcp_server.core.style_classifier import classify_style
from mcp_server.core.style_classifier_ema import update_style_ema


# ---------------------------------------------------------------------------
# classify_style
# ---------------------------------------------------------------------------


class TestClassifyStyle:
    def test_empty_input(self):
        style = classify_style([])
        assert style["activeReflective"] == 0
        assert style["sensingIntuitive"] == 0
        assert style["sequentialGlobal"] == 0
        assert isinstance(style["problemDecomposition"], str)
        assert isinstance(style["explorationStyle"], str)
        assert isinstance(style["verificationBehavior"], str)

    def test_none_input(self):
        style = classify_style(None)
        assert style["activeReflective"] == 0
        assert style["sensingIntuitive"] == 0
        assert style["sequentialGlobal"] == 0

    def test_valid_structure(self):
        convs = [
            {
                "toolsUsed": ["Edit", "Edit", "Write", "Read"],
                "duration": 5,
                "durationMinutes": 5,
                "summary": "try to fix the bug quickly",
                "filesTouched": ["src/a.js", "src/b.js"],
            },
        ]
        style = classify_style(convs)
        assert "activeReflective" in style
        assert "sensingIntuitive" in style
        assert "sequentialGlobal" in style
        assert "problemDecomposition" in style
        assert "explorationStyle" in style
        assert "verificationBehavior" in style
        assert -1 <= style["activeReflective"] <= 1
        assert -1 <= style["sensingIntuitive"] <= 1
        assert -1 <= style["sequentialGlobal"] <= 1

    def test_active_style(self):
        convs = [
            {
                "toolsUsed": ["Edit", "Edit", "Edit", "Write", "Read"],
                "durationMinutes": 5,
                "summary": "try quick iterate experiment tweak",
                "filesTouched": ["src/a.js"],
            }
            for _ in range(5)
        ]
        style = classify_style(convs)
        assert style["activeReflective"] > 0

    def test_reflective_style(self):
        convs = [
            {
                "toolsUsed": ["Read", "Read", "Read", "Grep", "Edit"],
                "durationMinutes": 45,
                "summary": "plan strategy review analyse evaluate consider",
                "filesTouched": ["src/a.js"],
            }
            for _ in range(5)
        ]
        style = classify_style(convs)
        assert style["activeReflective"] < 0

    def test_sensing_style(self):
        convs = [
            {
                "toolsUsed": [],
                "summary": "example specifically instance step-by-step file line function",
                "filesTouched": [f"src/file{i}.js" for i in range(10)],
            }
            for _ in range(5)
        ]
        style = classify_style(convs)
        assert style["sensingIntuitive"] > 0

    def test_intuitive_style(self):
        convs = [
            {
                "toolsUsed": [],
                "summary": "architecture pattern system design module abstraction principle paradigm framework",
                "filesTouched": [],
            }
            for _ in range(5)
        ]
        style = classify_style(convs)
        assert style["sensingIntuitive"] < 0

    def test_problem_decomposition_default(self):
        assert classify_style([])["problemDecomposition"] == "top-down"

    def test_exploration_style_default(self):
        assert classify_style([])["explorationStyle"] == "depth-first"

    def test_verification_behavior_default(self):
        assert classify_style([])["verificationBehavior"] == "no-test"

    def test_test_first_verification(self):
        convs = [
            {
                "toolsUsed": ["Read", "Read", "Grep", "Edit"],
                "allText": "write unit test assert expect coverage",
                "summary": "",
            }
            for _ in range(5)
        ]
        style = classify_style(convs)
        assert style["verificationBehavior"] == "test-first"

    def test_depth_first_exploration(self):
        convs = [
            {
                "toolsUsed": ["Read"] * 20,
                "filesTouched": ["src/a.js", "src/b.js"],
            }
            for _ in range(5)
        ]
        style = classify_style(convs)
        assert style["explorationStyle"] == "depth-first"

    def test_breadth_first_exploration(self):
        convs = [
            {
                "toolsUsed": ["Read", "Edit"],
                "filesTouched": [f"src/f{i}.js" for i in range(10)],
            }
            for _ in range(5)
        ]
        style = classify_style(convs)
        assert style["explorationStyle"] == "breadth-first"


# ---------------------------------------------------------------------------
# update_style_ema
# ---------------------------------------------------------------------------


class TestUpdateStyleEMA:
    def test_none_old_returns_new(self):
        obs = {
            "activeReflective": 0.5,
            "sensingIntuitive": -0.3,
            "sequentialGlobal": 0.1,
            "problemDecomposition": "bottom-up",
        }
        assert update_style_ema(None, obs) == obs

    def test_none_new_returns_old(self):
        old = {
            "activeReflective": 0.5,
            "sensingIntuitive": -0.3,
            "sequentialGlobal": 0.1,
            "problemDecomposition": "top-down",
        }
        assert update_style_ema(old, None) == old

    def test_blend_alpha_half(self):
        old = {
            "activeReflective": 1.0,
            "sensingIntuitive": 0,
            "sequentialGlobal": -1.0,
            "problemDecomposition": "top-down",
            "explorationStyle": "depth-first",
            "verificationBehavior": "no-test",
        }
        obs = {
            "activeReflective": -1.0,
            "sensingIntuitive": 0,
            "sequentialGlobal": 1.0,
            "problemDecomposition": "bottom-up",
            "explorationStyle": "breadth-first",
            "verificationBehavior": "test-first",
        }
        result = update_style_ema(old, obs, 0.5)
        assert abs(result["activeReflective"] - 0) < 0.001
        assert abs(result["sequentialGlobal"] - 0) < 0.001

    def test_alpha_01_preserves_old(self):
        old = {
            "activeReflective": 0.8,
            "sensingIntuitive": 0.6,
            "sequentialGlobal": -0.4,
            "problemDecomposition": "top-down",
            "explorationStyle": "depth-first",
            "verificationBehavior": "test-after",
        }
        obs = {
            "activeReflective": -0.8,
            "sensingIntuitive": -0.6,
            "sequentialGlobal": 0.4,
            "problemDecomposition": "bottom-up",
            "explorationStyle": "breadth-first",
            "verificationBehavior": "test-first",
        }
        result = update_style_ema(old, obs, 0.1)
        assert abs(result["activeReflective"] - 0.64) < 0.01
        assert result["problemDecomposition"] == "top-down"
        assert result["explorationStyle"] == "depth-first"
        assert result["verificationBehavior"] == "test-after"

    def test_categorical_switch_at_alpha_half(self):
        old = {
            "activeReflective": 0,
            "sensingIntuitive": 0,
            "sequentialGlobal": 0,
            "problemDecomposition": "top-down",
            "explorationStyle": "depth-first",
            "verificationBehavior": "no-test",
        }
        obs = {
            "activeReflective": 0,
            "sensingIntuitive": 0,
            "sequentialGlobal": 0,
            "problemDecomposition": "bottom-up",
            "explorationStyle": "breadth-first",
            "verificationBehavior": "test-first",
        }
        result = update_style_ema(old, obs, 0.5)
        assert result["problemDecomposition"] == "bottom-up"
        assert result["explorationStyle"] == "breadth-first"
        assert result["verificationBehavior"] == "test-first"

    def test_clamps_numeric(self):
        old = {"activeReflective": 1.0, "sensingIntuitive": -1.0, "sequentialGlobal": 0}
        obs = {"activeReflective": 1.0, "sensingIntuitive": -1.0, "sequentialGlobal": 0}
        result = update_style_ema(old, obs, 0.9)
        assert result["activeReflective"] <= 1.0
        assert result["sensingIntuitive"] >= -1.0

    def test_missing_fields_default_to_zero(self):
        old = {"activeReflective": 0.5}
        obs = {"sensingIntuitive": -0.3}
        result = update_style_ema(old, obs, 0.5)
        assert abs(result["activeReflective"] - 0.25) < 0.01
        assert abs(result["sensingIntuitive"] - (-0.15)) < 0.01
