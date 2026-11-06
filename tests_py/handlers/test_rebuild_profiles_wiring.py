"""What the rebuild_profiles handler passes on and reports, with every collaborator
replaced, so each argument and each reported field is pinned exactly."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from mcp_server.core.profile_rebuild_policy import ProfileBuild
from mcp_server.handlers.rebuild_profiles import handler

_MODULE = "mcp_server.handlers.rebuild_profiles"
_MEMORIES = [{"name": "m"}]
_BRAIN = {"index": 1}
_CLAUDE = [{"project": "-a"}]
_CODEX = [{"project": "-b", "source": "codex"}]


def _run(args, profiles=None):
    build = MagicMock(return_value=ProfileBuild(profiles=profiles or {}, outcomes=[]))
    skip = MagicMock(return_value=None)
    clock = SimpleNamespace(monotonic=MagicMock(side_effect=[100.0, 102.5]))
    with (
        patch(f"{_MODULE}._check_skip", skip),
        patch(f"{_MODULE}.time", clock),
        patch(f"{_MODULE}.load_profiles", return_value={"stored": True}),
        patch(f"{_MODULE}.discover_all_memories", return_value=_MEMORIES),
        patch(f"{_MODULE}.discover_conversations", return_value=_CLAUDE),
        patch(f"{_MODULE}.discover_codex_conversations", return_value=_CODEX),
        patch(f"{_MODULE}.load_brain_index", return_value=_BRAIN),
        patch(f"{_MODULE}.build_domain_profiles", build),
        patch(f"{_MODULE}.save_profiles"),
    ):
        result = asyncio.run(handler(args))
    return result, skip, build


def test_defaults_are_the_boolean_false():
    _, skip, build = _run({})
    assert skip.call_args.args[0] is False
    assert build.call_args.kwargs["replace_accumulated"] is False


def test_scans_and_stores_reach_the_assembler():
    _, _, build = _run({"domain": "d"})
    kwargs = build.call_args.kwargs
    assert kwargs["conversations"] == _CLAUDE + _CODEX
    assert kwargs["memories"] is _MEMORIES
    assert kwargs["brain_index"] is _BRAIN
    assert kwargs["existing_profiles"] == {"stored": True}
    assert kwargs["target_domain"] == "d"


def test_reports_duration_in_milliseconds_and_counts():
    result, _, _ = _run({}, profiles={"domains": {"x": {}}})
    assert result["duration"] == 2500
    assert result["domains"] == ["x"]
    assert (result["totalSessions"], result["totalMemories"]) == (2, 1)


def test_a_build_without_domains_reports_none():
    result, _, _ = _run({})
    assert result["domains"] == []
