"""Tests for normalize_event: Claude events pass through byte-identical;
Codex events (apply_patch, exec_command/shell_command, SubagentStart,
PreCompact/PostCompact) translate into what the lifecycle hooks read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_server.hooks.host_event import HostEventError, normalize_event

# One Claude-shaped fixture per module class this PR must not disturb,
# matching what each module's process_event/evaluate reads.
CLAUDE_FIXTURES = {
    "decision_gate": {
        "hook_event_name": "PreToolUse",
        "session_id": "s1",
        "cwd": "/repo",
        "tool_name": "Edit",
        "tool_input": {"file_path": "/repo/a.py", "old_string": "x", "new_string": "y"},
    },
    "post_tool_capture": {
        "hook_event_name": "PostToolUse",
        "session_id": "s1",
        "cwd": "/repo",
        "tool_name": "Bash",
        "tool_input": {"command": "git status"},
        "tool_response": "clean",
    },
    "preemptive_context": {
        "hook_event_name": "PostToolUse",
        "cwd": "/repo",
        "tool_name": "Read",
        "tool_input": {"file_path": "/repo/a.py"},
    },
    "agent_briefing": {
        "hook_event_name": "SubagentStart",
        "agent_name": "engineer",
        "prompt": "investigate the failing suite and report back",
        "transcript_path": "/repo/t.jsonl",
    },
    "compaction_checkpoint": {
        "hook_event_name": "Notification",
        "session_id": "s1",
        "transcript_path": "/repo/t.jsonl",
    },
    "session_start": {"hook_event_name": "SessionStart", "source": "startup"},
    "session_lifecycle": {"hook_event_name": "SessionEnd", "reason": "exit"},
}


@pytest.mark.parametrize(
    "fixture", CLAUDE_FIXTURES.values(), ids=CLAUDE_FIXTURES.keys()
)
def test_claude_event_passes_through_byte_identical(fixture: dict) -> None:
    result = normalize_event(fixture)
    assert len(result) == 1
    assert json.dumps(result[0], sort_keys=True) == json.dumps(fixture, sort_keys=True)


def test_unknown_tool_passes_through() -> None:
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "update_plan",
        "tool_input": {},
    }
    assert normalize_event(event) == [event]


@pytest.mark.parametrize(
    "tool_name,key", [("exec_command", "cmd"), ("shell_command", "command")]
)
def test_shell_tool_becomes_bash_with_resolved_cwd(
    tmp_path: Path, tool_name: str, key: str
) -> None:
    event = {
        "hook_event_name": "PreToolUse",
        "cwd": "/ignored",
        "tool_name": tool_name,
        "tool_input": {key: "git status", "workdir": str(tmp_path)},
    }
    result = normalize_event(event)
    assert len(result) == 1
    assert result[0]["tool_name"] == "Bash"
    assert result[0]["tool_input"]["command"] == "git status"
    assert result[0]["cwd"] == str(tmp_path)


def test_shell_tool_without_workdir_keeps_event_cwd() -> None:
    event = {
        "cwd": "/repo",
        "tool_name": "shell_command",
        "tool_input": {"command": "ls"},
    }
    result = normalize_event(event)
    assert result[0]["cwd"] == "/repo"


def test_shell_tool_falls_back_to_tool_input_cwd_when_no_workdir(
    tmp_path: Path,
) -> None:
    """Parity with zetetic-team-subagents' host_events.py: when Codex sends
    ``tool_input.cwd`` instead of ``workdir``, it must still resolve --
    ``exec_command {"cmd": "ls", "cwd": "sub"}`` under base ``/p`` must
    derive ``/p/sub``, not silently fall back to the base itself."""
    event = {
        "cwd": str(tmp_path),
        "tool_name": "exec_command",
        "tool_input": {"cmd": "ls", "cwd": "sub"},
    }
    result = normalize_event(event)
    assert result[0]["cwd"] == str(tmp_path / "sub")


def test_subagent_start_maps_agent_type_and_leaves_prompt_absent() -> None:
    event = {
        "hook_event_name": "SubagentStart",
        "agent_id": "a1",
        "agent_type": "engineer",
    }
    result = normalize_event(event)
    assert len(result) == 1
    assert result[0]["agent_name"] == "engineer"
    assert "prompt" not in result[0]


def test_precompact_passes_through_like_notification_compacted() -> None:
    event = {"hook_event_name": "PreCompact", "trigger": "auto", "session_id": "s1"}
    assert normalize_event(event) == [event]


def test_postcompact_passes_through_like_notification_compacted() -> None:
    event = {"hook_event_name": "PostCompact", "trigger": "manual", "session_id": "s1"}
    assert normalize_event(event) == [event]


def test_apply_patch_dispatches_to_host_patch(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("before\n")
    event = {
        "cwd": str(tmp_path),
        "tool_name": "apply_patch",
        "tool_input": {
            "command": (
                "*** Begin Patch\n*** Update File: a.py\n@@\n"
                "-before\n+after\n*** End Patch"
            )
        },
    }
    result = normalize_event(event)
    assert result[0]["tool_name"] == "Edit"
    assert result[0]["tool_input"]["new_string"] == "after\n"


def test_apply_patch_malformed_patch_raises_host_event_error(tmp_path: Path) -> None:
    event = {
        "cwd": str(tmp_path),
        "tool_name": "apply_patch",
        "tool_input": {
            "command": (
                "*** Begin Patch\n*** Update File: missing.py\n@@\n"
                "-x\n+y\n*** End Patch"
            )
        },
    }
    with pytest.raises(HostEventError):
        normalize_event(event)


def test_non_dict_event_raises() -> None:
    with pytest.raises(HostEventError):
        normalize_event(["not", "a", "dict"])  # type: ignore[arg-type]
