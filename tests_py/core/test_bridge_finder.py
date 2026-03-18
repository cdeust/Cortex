"""Tests for mcp_server.core.bridge_finder — ported from bridge-finder.test.js."""

from mcp_server.core.bridge_finder import find_bridges


def _make_profiles(domains=None):
    return {"domains": domains or {}}


def _make_domain(**overrides):
    base = {"projects": [], "label": "test"}
    base.update(overrides)
    return base


class TestFindBridges:
    def test_empty_profiles(self):
        assert find_bridges(_make_profiles(), {}, {}) == {}

    def test_no_cross_refs(self):
        profiles = _make_profiles(
            {
                "alpha": _make_domain(projects=["proj-a"]),
                "beta": _make_domain(projects=["proj-b"]),
            }
        )
        brain_index = {
            "memories": {
                "m1": {
                    "projectId": "proj-a",
                    "body": "no references here",
                    "crossRefs": [],
                },
                "m2": {
                    "projectId": "proj-b",
                    "body": "no references here either",
                    "crossRefs": [],
                },
            },
            "conversations": {},
        }
        assert find_bridges(profiles, brain_index) == {}

    def test_structural_bridges(self):
        profiles = _make_profiles(
            {
                "alpha": _make_domain(projects=["proj-a"]),
                "beta": _make_domain(projects=["proj-b"]),
            }
        )
        brain_index = {
            "memories": {
                "m1": {
                    "projectId": "proj-a",
                    "body": "alpha content",
                    "crossRefs": ["m2"],
                },
                "m2": {"projectId": "proj-b", "body": "beta content", "crossRefs": []},
            },
            "conversations": {},
        }
        result = find_bridges(profiles, brain_index)

        assert "alpha" in result
        assert "beta" in result

        alpha_bridge = next(
            (b for b in result["alpha"] if b["pattern"] == "structural-edge"), None
        )
        assert alpha_bridge is not None
        assert alpha_bridge["toDomain"] == "beta"
        assert alpha_bridge["weight"] > 0
        assert alpha_bridge["edgeCount"] >= 1

    def test_bidirectional_edges(self):
        profiles = _make_profiles(
            {
                "alpha": _make_domain(projects=["proj-a"]),
                "beta": _make_domain(projects=["proj-b"]),
            }
        )
        brain_index = {
            "memories": {
                "m1": {"projectId": "proj-a", "body": "", "crossRefs": ["m2"]},
                "m2": {"projectId": "proj-b", "body": "", "crossRefs": []},
            },
            "conversations": {},
        }
        result = find_bridges(profiles, brain_index)
        assert any(b["toDomain"] == "beta" for b in result.get("alpha", []))
        assert any(b["toDomain"] == "alpha" for b in result.get("beta", []))

    def test_ignores_same_domain(self):
        profiles = _make_profiles(
            {
                "alpha": _make_domain(projects=["proj-a"]),
            }
        )
        brain_index = {
            "memories": {
                "m1": {"projectId": "proj-a", "body": "", "crossRefs": ["m2"]},
                "m2": {"projectId": "proj-a", "body": "", "crossRefs": []},
            },
            "conversations": {},
        }
        assert find_bridges(profiles, brain_index) == {}

    def test_analogical_similar_to(self):
        profiles = _make_profiles(
            {
                "alpha": _make_domain(projects=["proj-a"]),
            }
        )
        brain_index = {
            "memories": {
                "m1": {
                    "projectId": "proj-a",
                    "body": "This approach is similar to the pattern used in microservices",
                    "crossRefs": [],
                },
            },
            "conversations": {},
        }
        result = find_bridges(profiles, brain_index)
        assert "alpha" in result
        analogy = next(
            (b for b in result["alpha"] if b["toDomain"] == "text-analogy"), None
        )
        assert analogy is not None
        assert analogy["pattern"] == "similar to"
        assert len(analogy["examples"]) > 0
        assert (
            "pattern used in microservices" in analogy["examples"][0]["targetConcept"]
        )

    def test_analogical_like(self):
        profiles = _make_profiles(
            {
                "beta": _make_domain(projects=["proj-b"]),
            }
        )
        brain_index = {
            "memories": {
                "m1": {
                    "projectId": "proj-b",
                    "body": "This works like a message queue for events",
                    "crossRefs": [],
                },
            },
            "conversations": {},
        }
        result = find_bridges(profiles, brain_index)
        assert "beta" in result
        bridge = next((b for b in result["beta"] if b["pattern"] == "like"), None)
        assert bridge is not None

    def test_analogical_reminds_me_of(self):
        profiles = _make_profiles(
            {
                "gamma": _make_domain(projects=["proj-g"]),
            }
        )
        brain_index = {
            "memories": {
                "m1": {
                    "projectId": "proj-g",
                    "body": "This reminds me of the observer pattern implementation",
                    "crossRefs": [],
                },
            },
            "conversations": {},
        }
        result = find_bridges(profiles, brain_index)
        assert "gamma" in result
        bridge = next(
            (b for b in result["gamma"] if b["pattern"] == "reminds me of"), None
        )
        assert bridge is not None

    def test_weighted_cross_refs(self):
        profiles = _make_profiles(
            {
                "alpha": _make_domain(projects=["proj-a"]),
                "beta": _make_domain(projects=["proj-b"]),
            }
        )
        brain_index = {
            "memories": {
                "m1": {
                    "projectId": "proj-a",
                    "body": "",
                    "crossRefs": [{"id": "m2", "weight": 3}],
                },
                "m2": {"projectId": "proj-b", "body": "", "crossRefs": []},
            },
            "conversations": {},
        }
        result = find_bridges(profiles, brain_index)
        alpha_bridge = next(
            b for b in result["alpha"] if b["pattern"] == "structural-edge"
        )
        assert alpha_bridge["weight"] == 3

    def test_merges_memories(self):
        profiles = _make_profiles(
            {
                "alpha": _make_domain(projects=["proj-a"]),
                "beta": _make_domain(projects=["proj-b"]),
            }
        )
        brain_index = {
            "memories": {
                "m1": {"projectId": "proj-a", "body": "", "crossRefs": ["m2"]},
            },
            "conversations": {},
        }
        extra = {"m2": {"projectId": "proj-b", "body": "", "crossRefs": []}}
        result = find_bridges(profiles, brain_index, extra)
        assert "alpha" in result

    def test_null_brain_index(self):
        profiles = _make_profiles({"alpha": _make_domain(projects=["proj-a"])})
        assert find_bridges(profiles, None, None) == {}

    def test_domain_id_fallback(self):
        profiles = _make_profiles(
            {
                "alpha": _make_domain(projects=[]),
                "beta": _make_domain(projects=[]),
            }
        )
        brain_index = {
            "memories": {
                "m1": {"domainId": "alpha", "body": "", "crossRefs": ["m2"]},
                "m2": {"domainId": "beta", "body": "", "crossRefs": []},
            },
            "conversations": {},
        }
        result = find_bridges(profiles, brain_index)
        assert "alpha" in result
        assert "beta" in result

    def test_examples_capped_at_5(self):
        profiles = _make_profiles(
            {
                "alpha": _make_domain(projects=["proj-a"]),
                "beta": _make_domain(projects=["proj-b"]),
            }
        )
        memories = {}
        for i in range(10):
            memories[f"a{i}"] = {
                "projectId": "proj-a",
                "body": "",
                "crossRefs": [f"b{i}"],
            }
            memories[f"b{i}"] = {"projectId": "proj-b", "body": "", "crossRefs": []}
        result = find_bridges(profiles, {"memories": memories, "conversations": {}})
        alpha_bridge = next(
            b for b in result["alpha"] if b["pattern"] == "structural-edge"
        )
        assert len(alpha_bridge["examples"]) <= 5
        assert alpha_bridge["edgeCount"] == 10
