"""Tests for mcp_server.handlers.explore_features — ported from explore-features.test.js."""

import asyncio
from unittest.mock import patch

from mcp_server.handlers.explore_features import handler, schema


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
        seed = {"K": 8, "D": 27, "sparsity": 3, "features": []}
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
            "featureDictionary": {"K": 8, "D": 27, "sparsity": 3, "features": []},
        }
        graph = {
            "nodes": [{"id": "n1", "layer": "feature", "label": "feat-a"}],
            "edges": [],
        }
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
            "featureDictionary": {"K": 8, "D": 27, "sparsity": 3, "features": []},
        }
        graph = {"nodes": [], "edges": []}
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
            "featureDictionary": {"K": 8, "D": 27, "features": []},
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
            "featureDictionary": {"K": 8, "D": 27, "features": []},
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
            "featureDictionary": {"K": 8, "D": 27, "features": []},
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
            "featureDictionary": {"K": 8, "D": 27, "features": []},
        }
        persistent = [{"feature": "shared-feat", "persistence": 0.8}]
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
        assert result["persistentFeatures"] == persistent
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
