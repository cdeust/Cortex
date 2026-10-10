"""rebuild_profiles must never lower a domain's accumulated evidence.

Claude Code deletes old transcripts, so a rescan sees a sliding window while
a stored profile accumulates one session per ``record_session_end``. A rescan
that sees fewer sessions than the profile records keeps the stored profile
and says so; replacing it is possible only through
``replace_accumulated_profiles``. Everything here runs against temp dirs.
"""

import asyncio
import json

import pytest
from mcp.server.mcpserver import MCPServer

from mcp_server import tool_registry_core
from mcp_server.handlers.rebuild_profiles import handler, schema
from mcp_server.infrastructure.profile_store import (
    load_profile,
    load_profiles,
    save_profile,
)
from mcp_server.validation.schemas import SCHEMAS

_MARKER = "accumulated-state-no-transcript-can-rebuild"


def _write_sessions(projects, project, count):
    proj_dir = projects / project
    proj_dir.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        lines = [
            json.dumps(
                {
                    "type": "user",
                    "slug": "s",
                    "cwd": str(proj_dir),
                    "timestamp": "2026-01-01T00:00:00Z",
                    "message": {"content": f"fix the bug number {i}"},
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "timestamp": "2026-01-01T00:05:00Z",
                    "message": {
                        "content": [{"type": "tool_use", "name": "Read", "input": {}}]
                    },
                }
            ),
        ]
        (proj_dir / f"s{i}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(args):
    return asyncio.run(handler(args))


def _domain_of(project):
    """Learn the domain id the real pipeline assigns to a project."""
    _run({"force": True})
    domains = [
        d_id
        for d_id, d in load_profiles()["domains"].items()
        if project in d["projects"]
    ]
    assert len(domains) == 1
    return domains[0]


def _store(domain, sessions):
    profile = dict(load_profile(domain) or {"id": domain, "projects": []})
    profile["sessionCount"] = sessions
    profile["accumulatedMarker"] = _MARKER
    save_profile(domain, profile)


@pytest.fixture
def window(hermetic_claude_dirs):
    """A scan window of 8 transcripts in one project; returns (domain_id,)."""
    _write_sessions(hermetic_claude_dirs / "projects", "proj-a", 8)
    return _domain_of("proj-a")


def _outcome(result, domain):
    matches = [o for o in result["domainOutcomes"] if o["domain"] == domain]
    assert len(matches) == 1
    return matches[0]


class TestRescanSeesFewerSessions:
    def test_stored_profile_is_kept(self, window):
        _store(window, 32)
        result = _run({"force": True})
        kept = load_profile(window)
        assert kept["sessionCount"] == 32
        assert kept["accumulatedMarker"] == _MARKER
        assert _outcome(result, window) == {
            "domain": window,
            "action": "kept",
            "storedSessions": 32,
            "scannedSessions": 8,
            "resultingSessions": 32,
        }

    def test_kept_profile_derived_fields_are_not_rewritten(self, window):
        _store(window, 32)
        before = load_profile(window)
        _run({"force": True})
        assert load_profile(window) == before

    def test_explicit_replace_replaces_and_reports_before_and_after(self, window):
        _store(window, 32)
        result = _run({"force": True, "replace_accumulated_profiles": True})
        replaced = load_profile(window)
        assert replaced["sessionCount"] == 8
        assert "accumulatedMarker" not in replaced
        assert _outcome(result, window) == {
            "domain": window,
            "action": "replaced",
            "storedSessions": 32,
            "scannedSessions": 8,
            "resultingSessions": 8,
        }

    def test_global_style_counts_the_kept_sessions_once(self, window):
        _store(window, 32)
        _run({"force": True})
        assert load_profiles()["globalStyle"]["sessionCount"] == 32


class TestRescanSeesAtLeastAsManySessions:
    @pytest.mark.parametrize("stored", [3, 8])
    def test_domain_is_rebuilt(self, window, stored):
        _store(window, stored)
        result = _run({"force": True})
        rebuilt = load_profile(window)
        assert rebuilt["sessionCount"] == 8
        assert "accumulatedMarker" not in rebuilt
        assert _outcome(result, window) == {
            "domain": window,
            "action": "rebuilt",
            "storedSessions": stored,
            "scannedSessions": 8,
            "resultingSessions": 8,
        }

    def test_new_domain_is_created(self, hermetic_claude_dirs):
        _write_sessions(hermetic_claude_dirs / "projects", "proj-new", 2)
        result = _run({"force": True})
        (outcome,) = result["domainOutcomes"]
        assert outcome["action"] == "created"
        assert outcome["storedSessions"] == 0
        assert outcome["scannedSessions"] == outcome["resultingSessions"] == 2


class TestDomainsTheScanDoesNotSee:
    def test_domain_without_conversations_is_untouched_and_unreported(self, window):
        other = {"id": "gone", "projects": ["-gone"], "sessionCount": 5, "x": 1}
        save_profile("gone", other)
        result = _run({"force": True})
        assert load_profile("gone") == other
        assert all(o["domain"] != "gone" for o in result["domainOutcomes"])

    def test_target_domain_limits_what_is_reported_and_touched(
        self, hermetic_claude_dirs
    ):
        projects = hermetic_claude_dirs / "projects"
        _write_sessions(projects, "proj-a", 8)
        _write_sessions(projects, "proj-b", 8)
        a, b = _domain_of("proj-a"), _domain_of("proj-b")
        _store(a, 32)
        _store(b, 32)
        result = _run({"force": True, "domain": a})
        assert [o["domain"] for o in result["domainOutcomes"]] == [a]
        assert load_profile(b)["sessionCount"] == 32


class TestMalformedStoredCount:
    @pytest.mark.parametrize("bad", ["32", 32.5, True, [32]])
    def test_non_integer_session_count_fails_hard(self, window, bad):
        _store(window, bad)
        with pytest.raises(ValueError, match="sessionCount"):
            _run({"force": True})
        assert load_profile(window)["sessionCount"] == bad

    def test_missing_session_count_means_no_recorded_evidence(self, window):
        profile = load_profile(window)
        del profile["sessionCount"]
        save_profile(window, profile)
        result = _run({"force": True})
        assert _outcome(result, window)["action"] == "rebuilt"
        assert _outcome(result, window)["storedSessions"] == 0


class TestToolContract:
    def test_description_no_longer_promises_a_from_scratch_rebuild(self):
        text = schema["description"]
        assert "from scratch" not in text
        assert "replace_accumulated_profiles" in text
        assert "force" in text

    def test_schema_declares_the_replace_parameter(self):
        prop = schema["inputSchema"]["properties"]["replace_accumulated_profiles"]
        assert prop["type"] == "boolean"
        assert prop["default"] is False
        assert "force" in schema["inputSchema"]["properties"]
        assert "force" in prop["description"]

    def test_validation_schema_accepts_the_replace_parameter(self):
        props = SCHEMAS["rebuild_profiles"]["properties"]
        assert props["replace_accumulated_profiles"]["type"] == "boolean"

    def test_force_alone_never_replaces(self, window):
        _store(window, 32)
        assert _run({"force": True})["domainOutcomes"][0]["action"] == "kept"


class TestRegisteredToolPath:
    """The value must survive the registered wrapper, not only the handler.

    A client reaches the handler through ``mcp.call_tool``. A wrapper that
    keeps the parameter but forwards a constant would pass every direct
    handler test above, so these go through the registered tool and read the
    stored profile back.
    """

    @staticmethod
    def _call(arguments):
        mcp = MCPServer(name="rebuild-profiles-registry-test")
        tool_registry_core._register_rebuild_profiles(mcp)
        asyncio.run(mcp.call_tool("rebuild_profiles", arguments))

    def test_true_reaches_the_handler_and_replaces(self, window):
        _store(window, 32)
        self._call({"force": True, "replace_accumulated_profiles": True})
        replaced = load_profile(window)
        assert replaced["sessionCount"] == 8
        assert "accumulatedMarker" not in replaced

    def test_force_alone_keeps_the_accumulated_profile(self, window):
        _store(window, 32)
        self._call({"force": True})
        kept = load_profile(window)
        assert kept["sessionCount"] == 32
        assert kept["accumulatedMarker"] == _MARKER
