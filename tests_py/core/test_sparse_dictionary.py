"""Tests for mcp_server.core.sparse_dictionary — ported from sparse-dictionary.test.js."""

from mcp_server.core.sparse_dictionary import (
    build_seed_dictionary,
    learn_dictionary,
    encode_session,
    label_feature,
)
from mcp_server.core.sparse_dictionary_activation import (
    SIGNAL_NAMES,
    D,
    extract_session_activation,
)
from mcp_server.core.sparse_dictionary_learning import omp
from mcp_server.shared.linear_algebra import norm, normalize


def _make_conv(**overrides):
    base = {
        "sessionId": "test-session",
        "toolsUsed": ["Read", "Edit", "Grep", "Bash"],
        "allText": "fix the bug in the authentication module",
        "firstMessage": "fix the auth bug",
        "duration": 600000,
        "turnCount": 10,
        "messageCount": 20,
        "keywords": {"authentication", "module"},
    }
    base.update(overrides)
    return base


def _make_conversations(n, **overrides):
    return [_make_conv(sessionId=f"session-{i}", **overrides) for i in range(n)]


class TestSignalNames:
    def test_has_27_dimensions(self):
        assert len(SIGNAL_NAMES) == 27
        assert D == 27

    def test_no_duplicates(self):
        assert len(set(SIGNAL_NAMES)) == len(SIGNAL_NAMES)


class TestExtractSessionActivation:
    def test_returns_27d_vector(self):
        result = extract_session_activation(_make_conv())
        assert len(result) == 27

    def test_all_values_finite(self):
        result = extract_session_activation(_make_conv())
        for v in result:
            assert isinstance(v, (int, float))
            assert v == v  # not NaN

    def test_tool_ratios_sum_to_1(self):
        result = extract_session_activation(
            _make_conv(toolsUsed=["Read", "Edit", "Read"])
        )
        tool_sum = sum(result[:7])
        assert abs(tool_sum - 1) < 0.01

    def test_handles_empty_conversation(self):
        result = extract_session_activation({})
        assert len(result) == 27

    def test_burst_indicator_for_short_sessions(self):
        result = extract_session_activation(_make_conv(duration=300000))
        assert result[13] == 1  # tmp:burst

    def test_exploration_indicator_for_high_turns(self):
        result = extract_session_activation(_make_conv(turnCount=30))
        assert result[14] == 1  # tmp:exploration


class TestBuildSeedDictionary:
    def test_valid_structure(self):
        d = build_seed_dictionary()
        assert d["K"] == 8
        assert d["D"] == 27
        assert d["sparsity"] == 3
        assert d["learnedFromSessions"] == 0
        assert len(d["features"]) == 8

    def test_all_atoms_unit_vectors(self):
        d = build_seed_dictionary()
        for f in d["features"]:
            n = norm(f["direction"])
            assert abs(n - 1) < 0.01, f"Norm of {f['label']}: {n}"

    def test_features_have_labels_and_descriptions(self):
        d = build_seed_dictionary()
        for f in d["features"]:
            assert len(f["label"]) > 0
            assert len(f["description"]) > 0
            assert len(f["topSignals"]) > 0


class TestOmp:
    def test_returns_empty_for_zero_signal(self):
        atoms = [normalize([1, 0, 0]), normalize([0, 1, 0])]
        result = omp([0, 0, 0], atoms, 2)
        assert len(result["indices"]) == 0

    def test_finds_correct_single_atom(self):
        atoms = [normalize([1, 0, 0]), normalize([0, 1, 0]), normalize([0, 0, 1])]
        result = omp([5, 0, 0], atoms, 1)
        assert len(result["indices"]) == 1
        assert result["indices"][0] == 0
        assert abs(result["coefficients"][0] - 5) < 0.01

    def test_respects_sparsity_constraint(self):
        atoms = [
            normalize([1, 0, 0]),
            normalize([0, 1, 0]),
            normalize([0, 0, 1]),
            normalize([1, 1, 0]),
        ]
        result = omp([1, 1, 1], atoms, 2)
        assert len(result["indices"]) <= 2

    def test_reconstructs_signal_with_low_error(self):
        atoms = [normalize([1, 0]), normalize([0, 1])]
        signal = [3, 4]
        result = omp(signal, atoms, 2)
        assert norm(result["residual"]) < 0.01


class TestLearnDictionary:
    def test_returns_seed_for_few_sessions(self):
        convs = _make_conversations(5)
        d = learn_dictionary(convs)
        assert d["learnedFromSessions"] == 0
        assert d["K"] == 8

    def test_returns_seed_for_null(self):
        d = learn_dictionary(None)
        assert d["learnedFromSessions"] == 0

    def test_learns_for_10_plus_sessions(self):
        convs = _make_conversations(
            15,
            toolsUsed=["Read", "Edit", "Grep", "Bash", "Glob"],
            allText="implement the new feature with proper testing and architecture design",
            duration=1200000,
            turnCount=15,
        )
        d = learn_dictionary(convs, {"K": 5, "sparsity": 2, "iterations": 2})
        assert d["learnedFromSessions"] == 15
        assert d["K"] <= 5
        assert d["D"] == 27
        assert d["sparsity"] == 2

    def test_all_learned_atoms_unit_vectors(self):
        convs = _make_conversations(12)
        d = learn_dictionary(convs, {"K": 4, "sparsity": 2, "iterations": 2})
        for f in d["features"]:
            n = norm(f["direction"])
            assert abs(n - 1) < 0.01, f"Norm: {n}"

    def test_features_have_auto_generated_labels(self):
        convs = _make_conversations(12)
        d = learn_dictionary(convs, {"K": 4, "sparsity": 2, "iterations": 2})
        for f in d["features"]:
            assert len(f["label"]) > 0
            assert len(f["description"]) > 0


class TestEncodeSession:
    def test_returns_sparse_activation(self):
        d = build_seed_dictionary()
        result = encode_session(_make_conv(), d)
        assert isinstance(result["weights"], dict)
        assert isinstance(result["reconstructionError"], (int, float))
        assert result["reconstructionError"] >= 0

    def test_respects_sparsity(self):
        d = build_seed_dictionary()
        result = encode_session(_make_conv(), d)
        assert len(result["weights"]) <= d["sparsity"]

    def test_weights_are_nonzero(self):
        d = build_seed_dictionary()
        result = encode_session(
            _make_conv(
                toolsUsed=["Edit", "Edit", "Edit", "Bash"],
                allText="fix the critical bug immediately",
                duration=180000,
            ),
            d,
        )
        for w in result["weights"].values():
            assert abs(w) > 1e-10


class TestLabelFeature:
    def test_generates_meaningful_label(self):
        direction = [0.0] * 27
        direction[1] = 0.8  # tool:Edit
        direction[13] = 0.5  # tmp:burst
        result = label_feature(normalize(direction), 0)
        assert len(result["label"]) > 0
        assert len(result["topSignals"]) > 0

    def test_handles_zero_direction(self):
        result = label_feature([0.0] * 27, 5)
        assert result["label"] == "feature-5"
