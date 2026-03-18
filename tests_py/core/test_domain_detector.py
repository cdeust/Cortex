"""Tests for mcp_server.core.domain_detector — ported from domain-detector.test.js."""

from mcp_server.core.domain_detector import detect_domain, map_project_to_domain


def _make_profiles(domains=None):
    return {"domains": domains or {}}


def _make_domain(**overrides):
    base = {
        "projects": [],
        "topKeywords": [],
        "categoryDistribution": {},
        "label": "test-domain",
        "sessionCount": 5,
        "confidence": 0.5,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# detect_domain
# ---------------------------------------------------------------------------


class TestDetectDomain:
    def test_cold_start_empty_profiles(self):
        result = detect_domain({"cwd": "/Users/dev/project"}, _make_profiles())
        assert result["coldStart"] is True
        assert result["domain"] is None
        assert result["confidence"] == 0
        assert result["isNew"] is False
        assert result["alternativeDomains"] == []
        assert isinstance(result["context"], str)

    def test_cold_start_none_profiles(self):
        result = detect_domain({"cwd": "/foo"}, None)
        assert result["coldStart"] is True
        assert result["domain"] is None

    def test_cold_start_no_profiles(self):
        result = detect_domain({}, None)
        assert result["coldStart"] is True

    def test_confident_match(self):
        profiles = _make_profiles(
            {
                "jarvis": _make_domain(
                    projects=["-Users-dev-jarvis"],
                    topKeywords=["scanner", "cognitive", "profiling"],
                    categoryDistribution={"architecture": 0.5, "feature": 0.5},
                ),
            }
        )
        result = detect_domain(
            {
                "cwd": "/Users/dev/jarvis",
                "first_message": "fix the scanner cognitive profiling module",
            },
            profiles,
        )
        assert result["coldStart"] is False
        assert result["domain"] == "jarvis"
        assert result["confidence"] >= 0.6
        assert result["isNew"] is False

    def test_tentative_match(self):
        profiles = _make_profiles(
            {
                "backend": _make_domain(
                    projects=["-Users-other-backend"],
                    topKeywords=["authentication", "endpoint", "middleware"],
                    categoryDistribution={},
                ),
            }
        )
        result = detect_domain(
            {"first_message": "fix the authentication endpoint middleware"},
            profiles,
        )
        assert result["coldStart"] is False
        assert result["isNew"] is False
        assert result["confidence"] >= 0.3

    def test_new_domain_no_match(self):
        profiles = _make_profiles(
            {
                "jarvis": _make_domain(
                    projects=["-Users-dev-jarvis"],
                    topKeywords=["scanner", "cognitive"],
                    categoryDistribution={},
                ),
            }
        )
        result = detect_domain({"cwd": "/totally/different/path"}, profiles)
        assert result["coldStart"] is False
        assert result["domain"] is None
        assert result["isNew"] is True
        assert result["alternativeDomains"] == []

    def test_project_only_match(self):
        profiles = _make_profiles(
            {
                "myapp": _make_domain(
                    projects=["-Users-dev-myapp"],
                    topKeywords=[],
                    categoryDistribution={},
                ),
            }
        )
        result = detect_domain({"project": "-Users-dev-myapp"}, profiles)
        assert result["coldStart"] is False
        assert result["confidence"] >= 0.3

    def test_alternatives_ordered_by_confidence(self):
        profiles = _make_profiles(
            {
                "alpha": _make_domain(
                    projects=["-Users-dev-alpha"],
                    topKeywords=["scanner", "profiling", "cognitive"],
                    categoryDistribution={"architecture": 0.8},
                ),
                "beta": _make_domain(
                    projects=[],
                    topKeywords=["scanner", "profiling"],
                    categoryDistribution={"architecture": 0.6},
                ),
                "gamma": _make_domain(
                    projects=[],
                    topKeywords=["scanner"],
                    categoryDistribution={"architecture": 0.3},
                ),
            }
        )
        result = detect_domain(
            {
                "cwd": "/Users/dev/alpha",
                "first_message": "update the scanner profiling architecture",
            },
            profiles,
        )
        assert result["domain"] == "alpha"
        alts = result["alternativeDomains"]
        for i in range(1, len(alts)):
            assert alts[i - 1]["confidence"] >= alts[i]["confidence"]

    def test_cwd_derives_project_id(self):
        profiles = _make_profiles(
            {
                "myproj": _make_domain(projects=["-Users-dev-myproj"], topKeywords=[]),
            }
        )
        result = detect_domain({"cwd": "/Users/dev/myproj"}, profiles)
        assert result["domain"] == "myproj"

    def test_empty_context(self):
        profiles = _make_profiles(
            {
                "d": _make_domain(projects=[], topKeywords=[]),
            }
        )
        result = detect_domain({}, profiles)
        assert result["coldStart"] is False
        assert result["confidence"] <= 0.3


# ---------------------------------------------------------------------------
# map_project_to_domain
# ---------------------------------------------------------------------------


class TestMapProjectToDomain:
    def test_finds_domain(self):
        profiles = _make_profiles(
            {
                "jarvis": _make_domain(
                    projects=["-Users-dev-jarvis", "-Users-dev-jarvis2"]
                ),
                "other": _make_domain(projects=["-Users-dev-other"]),
            }
        )
        assert map_project_to_domain("-Users-dev-jarvis", profiles) == "jarvis"
        assert map_project_to_domain("-Users-dev-other", profiles) == "other"

    def test_not_found(self):
        profiles = _make_profiles(
            {
                "jarvis": _make_domain(projects=["-Users-dev-jarvis"]),
            }
        )
        assert map_project_to_domain("-Users-dev-unknown", profiles) is None

    def test_none_project_id(self):
        assert map_project_to_domain(None, _make_profiles()) is None

    def test_none_profiles(self):
        assert map_project_to_domain("-foo", None) is None

    def test_no_domains_key(self):
        assert map_project_to_domain("-foo", {}) is None
