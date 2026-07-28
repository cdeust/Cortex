"""Tests for mcp_server.handlers.explore_features — ported from
explore-features.test.js."""

import asyncio
import json
from unittest.mock import patch

from mcp_server.handlers.explore_features import handler, schema
from mcp_server.shared.types_features import (
    AttributionGraph,
    AttributionNode,
    FeatureDictionary,
    PersistentFeature,
)


class TestExploreSchema:
    def test_requires_mode(self):
        assert "mode" in schema["inputSchema"]["required"]

    def test_has_description(self):
        assert len(schema["description"]) > 0

    def test_defines_mode_enum(self):
        mode_enum = schema["inputSchema"]["properties"]["mode"]["enum"]
        assert "features" in mode_enum
        assert "attribution" in mode_enum
        assert "persona" in mode_enum
        assert "crosscoder" in mode_enum


class TestExploreFeatures:
    def test_features_ok_or_no_data(self):
        result = asyncio.run(handler({"mode": "features"}))
        assert result["status"] in ("ok", "no_data")

    def test_features_returns_dictionary_when_profiles_exist(self):
        result = asyncio.run(handler({"mode": "features"}))
        if result["status"] == "ok":
            assert result["dictionary"] is not None
            assert isinstance(result["dictionary"]["K"], (int, float))
            assert isinstance(result["dictionary"]["D"], (int, float))
            assert isinstance(result["dictionary"]["features"], list)

    def test_features_with_mocked_profiles(self):
        seed_dict = {
            "K": 8,
            "D": 27,
            "sparsity": 3,
            "signalNames": [],
            "learnedFromSessions": 0,
            "features": [
                {
                    "index": 0,
                    "label": "test-feat",
                    "description": "desc",
                    "topSignals": [],
                }
            ],
        }
        profiles = {
            "domains": {"d1": {"label": "D1"}},
            "featureDictionary": seed_dict,
            "persistentFeatures": [{"feature": "test-feat"}],
        }
        with patch(
            "mcp_server.handlers.explore_features.load_profiles", return_value=profiles
        ):
            result = asyncio.run(handler({"mode": "features"}))
        assert result["status"] == "ok"
        assert result["dictionary"]["K"] == 8
        assert len(result["dictionary"]["features"]) == 1
        assert result["persistentFeatures"] == [{"feature": "test-feat"}]

    def test_features_uses_seed_dictionary_when_none(self):
        profiles = {"domains": {"d1": {"label": "D1"}}}
        seed = FeatureDictionary(
            K=8, D=27, sparsity=3, signalNames=[], features=[], learnedFromSessions=0
        )
        with (
            patch(
                "mcp_server.handlers.explore_features.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.explore_features.build_seed_dictionary",
                return_value=seed,
            ),
        ):
            result = asyncio.run(handler({"mode": "features"}))
        assert result["status"] == "ok"
        assert result["dictionary"]["K"] == 8


class TestExploreAttribution:
    def test_returns_graph_or_no_data(self):
        result = asyncio.run(handler({"mode": "attribution"}))
        assert result["status"] in ("ok", "no_data", "error")
        if result["status"] == "ok":
            assert result["graph"] is not None
            assert result["domain"] is not None

    def test_returns_error_for_unknown_domain(self):
        result = asyncio.run(
            handler(
                {"mode": "attribution", "domain": "definitely-not-a-real-domain-xyz"}
            )
        )
        assert result["status"] in ("error", "no_data")

    def test_attribution_enriches_activations(self):
        profiles = {
            "domains": {
                "d1": {
                    "label": "D1",
                    "featureActivations": {"feat-a": 0.9},
                }
            },
            "featureDictionary": {
                "K": 8,
                "D": 27,
                "sparsity": 3,
                "signalNames": [],
                "features": [],
                "learnedFromSessions": 0,
            },
        }
        graph = AttributionGraph(
            nodes=[
                AttributionNode(id="n1", layer="feature", label="feat-a", activation=0)
            ],
            edges=[],
        )
        with (
            patch(
                "mcp_server.handlers.explore_features.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.explore_features.trace_attribution",
                return_value=graph,
            ),
        ):
            result = asyncio.run(handler({"mode": "attribution", "domain": "d1"}))
        assert result["status"] == "ok"
        assert result["graph"]["nodes"][0]["activation"] == 0.9

    def test_attribution_defaults_to_first_domain(self):
        profiles = {
            "domains": {"first-dom": {"label": "First"}},
            "featureDictionary": {
                "K": 8,
                "D": 27,
                "sparsity": 3,
                "signalNames": [],
                "features": [],
                "learnedFromSessions": 0,
            },
        }
        graph = AttributionGraph(nodes=[], edges=[])
        with (
            patch(
                "mcp_server.handlers.explore_features.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.explore_features.trace_attribution",
                return_value=graph,
            ),
        ):
            result = asyncio.run(handler({"mode": "attribution"}))
        assert result["domain"] == "first-dom"


def _write_real_session(proj_dir, name):
    """Write a real-shaped JSONL session (used to prove the attribution
    mode is wired to a genuine on-disk source, not a fabricated graph)."""
    proj_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "type": "user",
                "slug": "s",
                "cwd": str(proj_dir),
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"content": "fix the bug in the auth module"},
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "timestamp": "2026-01-01T00:05:00Z",
                "message": {
                    "content": [{"type": "tool_use", "name": "Edit", "input": {}}]
                },
            }
        ),
    ]
    (proj_dir / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestExploreAttributionRealSource:
    """mode=attribution must trace real on-disk sessions when the domain
    has indexed projects, and stay honestly empty when it does not --
    the hollow-mode bug (trace_attribution always called with []) fixed
    by wiring discover_conversations_for_projects()."""

    def test_produces_non_empty_graph_from_real_sessions(self, tmp_path, monkeypatch):
        monkeypatch.setattr("mcp_server.infrastructure.scanner.CLAUDE_DIR", tmp_path)
        projects_dir = tmp_path / "projects"
        _write_real_session(projects_dir / "proj-a", "s1.jsonl")

        profiles = {
            "domains": {
                "d1": {
                    "label": "D1",
                    "confidence": 0.7,
                    "projects": ["proj-a"],
                    "metacognitive": {
                        "activeReflective": 0.3,
                        "sensingIntuitive": -0.2,
                        "sequentialGlobal": 0.5,
                        "problemDecomposition": "top-down",
                        "explorationStyle": "depth-first",
                        "verificationBehavior": "test-after",
                    },
                }
            },
            "featureDictionary": None,
        }
        with patch(
            "mcp_server.handlers.explore_features.load_profiles",
            return_value=profiles,
        ):
            result = asyncio.run(handler({"mode": "attribution", "domain": "d1"}))

        assert result["status"] == "ok"
        assert len(result["graph"]["nodes"]) > 0
        assert len(result["graph"]["edges"]) > 0
        edit_node = next(
            n for n in result["graph"]["nodes"] if n["id"] == "input:tool:Edit"
        )
        assert edit_node["activation"] > 0

    def test_empty_graph_when_domain_has_no_indexed_projects(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("mcp_server.infrastructure.scanner.CLAUDE_DIR", tmp_path)
        profiles = {
            "domains": {
                "d1": {
                    "label": "D1",
                    "confidence": 0.7,
                    "metacognitive": {},
                    # no "projects" key -- nothing indexed for this domain
                }
            },
            "featureDictionary": None,
        }
        with patch(
            "mcp_server.handlers.explore_features.load_profiles",
            return_value=profiles,
        ):
            result = asyncio.run(handler({"mode": "attribution", "domain": "d1"}))

        assert result["status"] == "ok"
        assert result["graph"]["nodes"] == []
        assert result["graph"]["edges"] == []

    def test_classifier_activation_is_always_numeric(self, tmp_path, monkeypatch):
        """The 3 categorical classifiers (problemDecomposition/
        explorationStyle/verificationBehavior) must not leak their string
        category into the numeric `activation` field."""
        monkeypatch.setattr("mcp_server.infrastructure.scanner.CLAUDE_DIR", tmp_path)
        projects_dir = tmp_path / "projects"
        _write_real_session(projects_dir / "proj-a", "s1.jsonl")

        profiles = {
            "domains": {
                "d1": {
                    "label": "D1",
                    "confidence": 0.7,
                    "projects": ["proj-a"],
                    "metacognitive": {
                        "activeReflective": 0.3,
                        "sensingIntuitive": -0.2,
                        "sequentialGlobal": 0.5,
                        "problemDecomposition": "top-down",
                        "explorationStyle": "depth-first",
                        "verificationBehavior": "test-after",
                    },
                }
            },
            "featureDictionary": None,
        }
        with patch(
            "mcp_server.handlers.explore_features.load_profiles",
            return_value=profiles,
        ):
            result = asyncio.run(handler({"mode": "attribution", "domain": "d1"}))

        nodes_by_id = {n["id"]: n for n in result["graph"]["nodes"]}
        for cls, expected_value in [
            ("problemDecomposition", "top-down"),
            ("explorationStyle", "depth-first"),
            ("verificationBehavior", "test-after"),
        ]:
            node = nodes_by_id[f"classifier:{cls}"]
            assert isinstance(node["activation"], float)
            assert node["activation"] == 0.0
            assert node["categoricalValue"] == expected_value

        for cls, expected_activation in [
            ("activeReflective", 0.3),
            ("sensingIntuitive", -0.2),
            ("sequentialGlobal", 0.5),
        ]:
            node = nodes_by_id[f"classifier:{cls}"]
            assert isinstance(node["activation"], float)
            assert node["activation"] == expected_activation
            assert node["categoricalValue"] is None


class TestExplorePersona:
    def test_returns_persona_or_no_data(self):
        result = asyncio.run(handler({"mode": "persona"}))
        assert result["status"] in ("ok", "no_data")
        if result["status"] == "ok":
            assert result["dimensions"] is not None
            assert "domains" in result or "persona" in result

    def test_returns_error_for_unknown_domain(self):
        result = asyncio.run(
            handler({"mode": "persona", "domain": "definitely-not-a-real-domain-xyz"})
        )
        assert result["status"] in ("error", "no_data")

    def test_persona_single_domain(self):
        persona_vec = {"dimensions": {"d1": 0.5}}
        profiles = {
            "domains": {"my-dom": {"label": "My", "personaVector": persona_vec}}
        }
        with patch(
            "mcp_server.handlers.explore_features.load_profiles", return_value=profiles
        ):
            result = asyncio.run(handler({"mode": "persona", "domain": "my-dom"}))
        assert result["status"] == "ok"
        assert result["persona"] == persona_vec

    def test_persona_all_domains(self):
        pv1 = {"d": [0.5]}
        pv2 = {"d": [0.3]}
        profiles = {
            "domains": {
                "dom1": {"label": "D1", "personaVector": pv1, "sessionCount": 10},
                "dom2": {"label": "D2", "personaVector": pv2, "sessionCount": 5},
            }
        }
        global_persona = {"d": [0.4]}
        with (
            patch(
                "mcp_server.handlers.explore_features.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.explore_features.compose_personas",
                return_value=global_persona,
            ),
        ):
            result = asyncio.run(handler({"mode": "persona"}))
        assert result["status"] == "ok"
        assert "dom1" in result["domains"]
        assert "dom2" in result["domains"]
        assert result["global"] == global_persona

    def test_persona_builds_when_not_stored(self):
        profiles = {"domains": {"dom1": {"label": "D1", "sessionCount": 5}}}
        built_persona = {"d": [0.1]}
        with (
            patch(
                "mcp_server.handlers.explore_features.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.explore_features.build_persona_vector",
                return_value=built_persona,
            ),
            patch(
                "mcp_server.handlers.explore_features.compose_personas",
                return_value=built_persona,
            ),
        ):
            result = asyncio.run(handler({"mode": "persona"}))
        assert result["status"] == "ok"
        assert result["domains"]["dom1"] == built_persona


class TestExploreCrosscoder:
    def test_returns_persistent_or_no_data(self):
        result = asyncio.run(handler({"mode": "crosscoder"}))
        assert result["status"] in ("ok", "no_data")
        if result["status"] == "ok":
            assert isinstance(result["persistentFeatures"], list)

    def test_returns_error_for_unknown_comparison(self):
        result = asyncio.run(
            handler(
                {
                    "mode": "crosscoder",
                    "domain": "definitely-not-a-real-domain-xyz",
                    "compare_domain": "also-not-real",
                }
            )
        )
        assert result["status"] in ("error", "no_data")

    def test_crosscoder_comparison_mode(self):
        profiles = {
            "domains": {
                "dom-a": {"label": "A", "featureActivations": {"f1": 0.9}},
                "dom-b": {"label": "B", "featureActivations": {"f1": 0.7}},
            },
            "featureDictionary": {
                "K": 8,
                "D": 27,
                "sparsity": 3,
                "signalNames": [],
                "features": [],
                "learnedFromSessions": 0,
            },
        }
        comparison = {"shared": ["f1"], "divergent": []}
        with (
            patch(
                "mcp_server.handlers.explore_features.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.explore_features.compare_feature_profiles",
                return_value=comparison,
            ),
        ):
            result = asyncio.run(
                handler(
                    {
                        "mode": "crosscoder",
                        "domain": "dom-a",
                        "compare_domain": "dom-b",
                    }
                )
            )
        assert result["status"] == "ok"
        assert result["comparison"]["domainA"] == "dom-a"
        assert result["comparison"]["domainB"] == "dom-b"
        assert result["comparison"]["shared"] == ["f1"]

    def test_crosscoder_error_missing_domain_a(self):
        profiles = {
            "domains": {"dom-b": {"label": "B"}},
            "featureDictionary": {
                "K": 8,
                "D": 27,
                "sparsity": 3,
                "signalNames": [],
                "features": [],
                "learnedFromSessions": 0,
            },
        }
        with patch(
            "mcp_server.handlers.explore_features.load_profiles", return_value=profiles
        ):
            result = asyncio.run(
                handler(
                    {
                        "mode": "crosscoder",
                        "domain": "missing-a",
                        "compare_domain": "dom-b",
                    }
                )
            )
        assert result["status"] == "error"
        assert "missing-a" in result["message"]

    def test_crosscoder_error_missing_domain_b(self):
        profiles = {
            "domains": {"dom-a": {"label": "A"}},
            "featureDictionary": {
                "K": 8,
                "D": 27,
                "sparsity": 3,
                "signalNames": [],
                "features": [],
                "learnedFromSessions": 0,
            },
        }
        with patch(
            "mcp_server.handlers.explore_features.load_profiles", return_value=profiles
        ):
            result = asyncio.run(
                handler(
                    {
                        "mode": "crosscoder",
                        "domain": "dom-a",
                        "compare_domain": "missing-b",
                    }
                )
            )
        assert result["status"] == "error"
        assert "missing-b" in result["message"]

    def test_crosscoder_persistent_features_fallback(self):
        profiles = {
            "domains": {"d1": {"label": "D1"}, "d2": {"label": "D2"}},
            "featureDictionary": {
                "K": 8,
                "D": 27,
                "sparsity": 3,
                "signalNames": [],
                "features": [],
                "learnedFromSessions": 0,
            },
        }
        persistent = [
            PersistentFeature(
                label="shared-feat",
                persistence=0.8,
                consistency=0.0,
                domains=["d1", "d2"],
            )
        ]
        with (
            patch(
                "mcp_server.handlers.explore_features.load_profiles",
                return_value=profiles,
            ),
            patch(
                "mcp_server.handlers.explore_features.detect_persistent_features",
                return_value=persistent,
            ),
        ):
            result = asyncio.run(handler({"mode": "crosscoder"}))
        assert result["status"] == "ok"
        assert result["persistentFeatures"] == [pf.model_dump() for pf in persistent]
        assert result["domainCount"] == 2


class TestExploreNoData:
    def test_returns_no_data_when_empty_profiles(self):
        with patch(
            "mcp_server.handlers.explore_features.load_profiles", return_value={}
        ):
            result = asyncio.run(handler({"mode": "features"}))
        assert result["status"] == "no_data"

    def test_returns_no_data_when_no_domains(self):
        with patch(
            "mcp_server.handlers.explore_features.load_profiles",
            return_value={"domains": {}},
        ):
            result = asyncio.run(handler({"mode": "features"}))
        assert result["status"] == "no_data"

    def test_returns_no_data_when_domains_is_none(self):
        with patch(
            "mcp_server.handlers.explore_features.load_profiles",
            return_value={"domains": None},
        ):
            result = asyncio.run(handler({"mode": "features"}))
        assert result["status"] == "no_data"


class TestExploreUnknownMode:
    def test_returns_error(self):
        result = asyncio.run(handler({"mode": "unknown_mode_xyz"}))
        assert result["status"] in ("error", "no_data")

    def test_unknown_mode_includes_mode_name(self):
        profiles = {"domains": {"d1": {"label": "D1"}}}
        with patch(
            "mcp_server.handlers.explore_features.load_profiles", return_value=profiles
        ):
            result = asyncio.run(handler({"mode": "bogus"}))
        assert result["status"] == "error"
        assert "bogus" in result["message"]
