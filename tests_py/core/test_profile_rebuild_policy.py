"""Rebuild-versus-keep policy: a rescan never lowers a domain's evidence."""

import copy

import pytest

from mcp_server.core.profile_assembler import build_domain_profiles
from mcp_server.core.profile_rebuild_policy import (
    decide_domain_outcome,
    stored_session_count,
)


def _conv(i=0):
    return {
        "sessionId": f"s{i}",
        "project": "-Users-dev-cortex",
        "firstMessage": f"fix bug {i}",
        "allText": f"fix bug {i} in the scanner",
        "keywords": ["bug", "scanner"],
        "toolUsage": {"Read": 2, "Edit": 1},
        "startedAt": "2026-01-01T00:00:00Z",
        "endedAt": "2026-01-01T00:10:00Z",
        "duration": 600000,
        "turnCount": 6,
    }


def _stored(sessions, **extra):
    return {
        "id": "cortex",
        "projects": ["-Users-dev-cortex"],
        "sessionCount": sessions,
        "confidence": 0.9,
        "metacognitive": {"activeReflective": 0.9, "sensingIntuitive": 0.1},
        "featureActivations": {"stored": 1.0},
        "personaVector": [9.0],
        "blindSpots": ["stored"],
        "connectionBridges": ["stored"],
        **extra,
    }


def _build(stored, scanned, **kwargs):
    convs = [_conv(i) for i in range(scanned)]
    profiles = {"domains": {"cortex": stored} if stored is not None else {}}
    return build_domain_profiles(
        existing_profiles=profiles,
        conversations=convs,
        memories={},
        brain_index={"memories": {}, "conversations": {}},
        by_project={"-Users-dev-cortex": convs},
        **kwargs,
    )


class TestStoredSessionCount:
    def test_no_profile_is_zero(self):
        assert stored_session_count("d", None) == 0
        assert stored_session_count("d", {}) == 0

    def test_absent_or_null_count_is_zero(self):
        assert stored_session_count("d", {"id": "d"}) == 0
        assert stored_session_count("d", {"sessionCount": None}) == 0

    def test_integer_count(self):
        assert stored_session_count("d", {"sessionCount": 32}) == 32

    @pytest.mark.parametrize("bad", ["32", 3.5, True, -1, [1]])
    def test_malformed_count_raises_naming_the_domain(self, bad):
        with pytest.raises(ValueError, match="'d'.*sessionCount"):
            stored_session_count("d", {"sessionCount": bad})


class TestDecideDomainOutcome:
    def test_nothing_stored_is_created(self):
        o = decide_domain_outcome("d", None, 8, False)
        assert (o.action, o.stored_sessions, o.resulting_sessions) == ("created", 0, 8)

    def test_scan_with_more_sessions_rebuilds(self):
        o = decide_domain_outcome("d", {"sessionCount": 3}, 8, False)
        assert (o.action, o.resulting_sessions) == ("rebuilt", 8)

    def test_scan_with_equal_sessions_rebuilds(self):
        o = decide_domain_outcome("d", {"sessionCount": 8}, 8, False)
        assert o.action == "rebuilt"

    def test_scan_with_fewer_sessions_keeps(self):
        o = decide_domain_outcome("d", {"sessionCount": 32}, 8, False)
        assert (o.action, o.stored_sessions, o.scanned_sessions) == ("kept", 32, 8)
        assert o.resulting_sessions == 32

    def test_scan_with_fewer_sessions_replaces_only_on_request(self):
        o = decide_domain_outcome("d", {"sessionCount": 32}, 8, True)
        assert (o.action, o.stored_sessions, o.resulting_sessions) == (
            "replaced",
            32,
            8,
        )

    def test_replace_request_does_not_relabel_a_plain_rebuild(self):
        o = decide_domain_outcome("d", {"sessionCount": 3}, 8, True)
        assert o.action == "rebuilt"

    def test_to_dict_uses_the_wire_names(self):
        assert decide_domain_outcome("d", {"sessionCount": 32}, 8, False).to_dict() == {
            "domain": "d",
            "action": "kept",
            "storedSessions": 32,
            "scannedSessions": 8,
            "resultingSessions": 32,
        }


class TestBuildDomainProfilesKeepsAccumulatedEvidence:
    def test_kept_profile_is_untouched_in_every_field(self):
        stored = _stored(32)
        expected = copy.deepcopy(stored)
        build = _build(stored, 8)
        assert build.profiles["domains"]["cortex"] == expected
        assert [o.action for o in build.outcomes] == ["kept"]

    def test_replace_builds_from_the_scan(self):
        build = _build(_stored(32), 8, replace_accumulated=True)
        domain = build.profiles["domains"]["cortex"]
        assert domain["sessionCount"] == 8
        assert domain["blindSpots"] != ["stored"]
        assert [o.action for o in build.outcomes] == ["replaced"]

    def test_scan_with_more_sessions_rebuilds(self):
        build = _build(_stored(3), 8)
        assert build.profiles["domains"]["cortex"]["sessionCount"] == 8
        assert [o.action for o in build.outcomes] == ["rebuilt"]

    def test_global_style_weights_the_kept_domain_by_its_stored_count(self):
        build = _build(_stored(32), 8)
        style = build.profiles["globalStyle"]
        assert style["sessionCount"] == 32
        assert style["activeReflective"] == 0.9

    def test_global_style_after_replace_counts_the_scan(self):
        build = _build(_stored(32), 8, replace_accumulated=True)
        assert build.profiles["globalStyle"]["sessionCount"] == 8

    def test_no_scanned_conversations_leaves_stored_profiles_and_reports_nothing(self):
        stored = _stored(32)
        expected = copy.deepcopy(stored)
        profiles = {"domains": {"cortex": stored}}
        build = build_domain_profiles(
            existing_profiles=profiles,
            conversations=[],
            memories={},
            brain_index=None,
            by_project={},
        )
        assert build.profiles["domains"]["cortex"] == expected
        assert build.outcomes == []

    def test_malformed_stored_count_aborts_the_build(self):
        with pytest.raises(ValueError, match="sessionCount"):
            _build(_stored("many"), 8)
