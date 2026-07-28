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

    # ── issue #95: Windows casing mismatch ───────────────────────────────

    def test_structural_bridge_resolves_despite_windows_casing_mismatch(self):
        # Profile stores original casing ('Proj-A'); the memory's
        # projectId was derived via cwd_to_project_id, which lowercases
        # Windows-style paths ('proj-a'). Before the fix, _resolve_domain
        # fell through to "unknown" and same-domain self-references (m1,
        # m2 both "unknown") were silently dropped as not cross-domain.
        profiles = _make_profiles(
            {
                "alpha": _make_domain(projects=["Proj-A"]),
                "beta": _make_domain(projects=["Proj-B"]),
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
        assert result["alpha"][0]["toDomain"] == "beta"

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
                    "body": "This approach is similar to the pattern "
                    "used in microservices",
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


def _scanner_memory_record(project: str, body: str = "") -> dict:
    """A memory record in the exact 9-key shape emitted by the scanner.

    Mirrors ``scanner._parse_memory_file`` — the production producer whose
    list output reached ``find_bridges`` and blew up in issue #174.
    """
    return {
        "file": "note.md",
        "path": f"/home/u/.claude/projects/{project}/memory/note.md",
        "project": project,
        "name": "note",
        "description": "",
        "type": "note",
        "body": body,
        "modifiedAt": "2026-07-23T02:57:21.806511Z",
        "createdAt": "2026-07-23T02:57:21.806511Z",
    }


class TestFindBridgesScannerListShape:
    """Regression pin for issue #174.

    ``discover_all_memories()`` returns a ``list`` of records, but
    ``find_bridges`` fed it straight into ``dict.update``. A non-empty list of
    records (each with 9 keys) raised ``ValueError: dictionary update sequence
    element #0 has length 9; 2 is required``. Empty homes skipped the branch,
    so CI stayed green while every real ``~/.claude`` failed.
    """

    def test_minimized_failing_input_no_longer_raises(self):
        # source: minimized from the live-home stack captured on 2026-07-24
        # (issue #174); a single 9-key scanner record is the smallest input
        # that reproduces the ValueError.
        profiles = _make_profiles({"alpha": _make_domain(projects=["proj-a"])})
        memories = [_scanner_memory_record("proj-a")]

        result = find_bridges(profiles, None, memories)

        assert isinstance(result, dict)

    def test_scanner_list_yields_analogical_bridge(self):
        profiles = _make_profiles(
            {
                "alpha": _make_domain(projects=["proj-a"]),
                "beta": _make_domain(projects=["proj-b"]),
            }
        )
        memories = [
            _scanner_memory_record(
                "proj-a", body="the write gate works just as a free energy filter"
            ),
        ]

        result = find_bridges(profiles, None, memories)

        assert "alpha" in result
        analog = next(b for b in result["alpha"] if b["toDomain"] == "text-analogy")
        assert analog["pattern"] == "just as"

    def test_scanner_list_and_brain_index_dict_merge(self):
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
        list_memories = [_scanner_memory_record("proj-a", body="")]

        result = find_bridges(profiles, brain_index, list_memories)

        assert "alpha" in result
        assert any(b["pattern"] == "structural-edge" for b in result["alpha"])

    def test_empty_list_is_noop(self):
        profiles = _make_profiles({"alpha": _make_domain(projects=["proj-a"])})
        assert find_bridges(profiles, None, []) == {}
