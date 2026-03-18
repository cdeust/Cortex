"""Tests for mcp_server.core.behavioral_crosscoder — ported from behavioral-crosscoder.test.js."""

from mcp_server.core.behavioral_crosscoder import (
    detect_persistent_features,
    compare_feature_profiles,
)


def _make_dictionary(feature_labels=None):
    if feature_labels is None:
        feature_labels = ["reading", "editing", "testing"]
    return {
        "K": len(feature_labels),
        "D": 27,
        "sparsity": 3,
        "signalNames": [],
        "features": [
            {
                "index": i,
                "label": label,
                "description": f"{label} feature",
                "direction": [0.0] * 27,
                "topSignals": [],
            }
            for i, label in enumerate(feature_labels)
        ],
        "learnedFromSessions": 10,
    }


def _make_activation(weights):
    return {"weights": weights, "reconstructionError": 0.1}


class TestDetectPersistentFeatures:
    def test_empty_for_no_profiles(self):
        d = _make_dictionary()
        assert detect_persistent_features({}, d) == []

    def test_empty_for_single_domain(self):
        d = _make_dictionary()
        assert detect_persistent_features({"domain-a": {}}, d) == []

    def test_empty_for_null_dictionary(self):
        profiles = {"domain-a": {}, "domain-b": {}}
        assert detect_persistent_features(profiles, None) == []

    def test_detects_feature_in_all_domains(self):
        d = _make_dictionary(["reading", "editing"])
        profiles = {"domain-a": {}, "domain-b": {}, "domain-c": {}}
        activations = {
            "domain-a": [_make_activation({"reading": 0.5})],
            "domain-b": [_make_activation({"reading": 0.4})],
            "domain-c": [_make_activation({"reading": 0.6})],
        }
        result = detect_persistent_features(profiles, d, activations)
        assert len(result) >= 1
        reading = next((f for f in result if f["label"] == "reading"), None)
        assert reading is not None
        assert reading["persistence"] == 1
        assert len(reading["domains"]) == 3

    def test_excludes_below_persistence_threshold(self):
        d = _make_dictionary(["reading", "editing"])
        profiles = {"domain-a": {}, "domain-b": {}, "domain-c": {}}
        activations = {
            "domain-a": [_make_activation({"editing": 0.5})],
            "domain-b": [_make_activation({})],
            "domain-c": [_make_activation({})],
        }
        result = detect_persistent_features(profiles, d, activations)
        editing = next((f for f in result if f["label"] == "editing"), None)
        assert editing is None

    def test_sorts_by_persistence_then_consistency(self):
        d = _make_dictionary(["a", "b"])
        profiles = {"d1": {}, "d2": {}, "d3": {}, "d4": {}}
        activations = {
            "d1": [_make_activation({"a": 0.5, "b": 0.3})],
            "d2": [_make_activation({"a": 0.5, "b": 0.3})],
            "d3": [_make_activation({"a": 0.5, "b": 0.3})],
            "d4": [_make_activation({"b": 0.3})],
        }
        result = detect_persistent_features(profiles, d, activations)
        if len(result) >= 2:
            assert result[0]["persistence"] >= result[1]["persistence"]

    def test_uses_profile_fallback(self):
        d = _make_dictionary(["reading"])
        profiles = {
            "domain-a": {"featureActivations": {"reading": 0.5}},
            "domain-b": {"featureActivations": {"reading": 0.4}},
        }
        result = detect_persistent_features(profiles, d)
        assert len(result) >= 1


class TestCompareFeatureProfiles:
    def test_partitions_features(self):
        d = _make_dictionary(["reading", "editing", "testing"])
        a = {"reading": 0.5, "editing": 0.3}
        b = {"editing": 0.4, "testing": 0.6}
        result = compare_feature_profiles(a, b, d)
        assert result["shared"] == ["editing"]
        assert result["uniqueToA"] == ["reading"]
        assert result["uniqueToB"] == ["testing"]

    def test_empty_for_no_active_features(self):
        d = _make_dictionary()
        result = compare_feature_profiles({}, {}, d)
        assert result["shared"] == []
        assert result["uniqueToA"] == []
        assert result["uniqueToB"] == []

    def test_ignores_below_threshold(self):
        d = _make_dictionary(["reading"])
        result = compare_feature_profiles({"reading": 0.05}, {"reading": 0.05}, d)
        assert result["shared"] == []

    def test_handles_null(self):
        d = _make_dictionary()
        result = compare_feature_profiles(None, None, d)
        assert result["shared"] == []
