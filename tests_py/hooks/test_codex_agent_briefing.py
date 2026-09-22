"""Native child context regressions, sourced to ADR-1085."""

import json
from unittest.mock import MagicMock, patch

import pytest

from mcp_server.hooks import agent_briefing as hook


def run(event):
    with pytest.raises(SystemExit) as exc:
        hook.process_event(event)
    assert exc.value.code == 0


def test_native_start_without_prompt_briefs_generic_worker(capsys):
    event = {
        "hook_event_name": "SubagentStart",
        "agent_type": "worker",
        "cwd": "/project",
    }
    with (
        patch.object(hook, "_connect", return_value=MagicMock()),
        patch.object(
            hook,
            "_fetch_role_context",
            return_value=[{"id": 1, "content": "Project policy", "source": "team"}],
        ),
    ):
        run(event)
    assert "Project policy" in capsys.readouterr().out


def test_spawn_preserves_every_argument_and_message(capsys):
    arguments = {
        "message": "Improve reranker latency now",
        "agent_type": "worker",
        "fork_context": False,
        "custom": {"x": [1]},
        "sandbox_permissions": "use_default",
        "allowed_tools": ["read_file"],
    }
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "spawn_agent",
        "tool_input": arguments,
        "cwd": "/project",
    }
    original = json.loads(json.dumps(arguments))
    with (
        patch.object(hook, "_connect", return_value=MagicMock()),
        patch.object(
            hook,
            "_fetch_agent_context",
            return_value=[{"id": 1, "content": "Reranker policy", "source": "team"}],
        ),
    ):
        run(event)
    output = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert output["permissionDecision"] == "allow"
    updated = output["updatedInput"]
    assert updated.pop("message").startswith(original["message"] + "\n\n")
    assert updated == {k: v for k, v in original.items() if k != "message"}
    assert arguments == original


@pytest.mark.parametrize("tool", ["spawn_agent", "Agent"])
def test_two_task_requests_keep_their_own_keywords_and_project(
    tool, capsys, monkeypatch
):
    monkeypatch.delenv("CLAUDE_PROJECT_ROOT", raising=False)
    calls = []

    def fetch(conn, agent, keywords, project):
        calls.append((agent, keywords, project))
        return [
            {"id": 1, "content": f"{project}:{keywords[0]}", "source": "agent-prior"}
        ]

    with (
        patch.object(hook, "_connect", return_value=MagicMock()),
        patch.object(hook, "_fetch_agent_context", side_effect=fetch),
        patch.object(hook, "emit_hook_receipt", return_value=None),
    ):
        for task, project in [("orchid latency", "/a"), ("violet storage", "/b")]:
            run(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": tool,
                    "tool_input": {"message": task, "agent_type": "worker"},
                    "cwd": project,
                    "transcript_path": "/unrelated/transcript",
                }
            )
    outputs = [
        json.loads(line)["hookSpecificOutput"]["updatedInput"]["message"]
        for line in capsys.readouterr().out.splitlines()
    ]
    assert calls == [
        ("worker", ["orchid", "latency"], "/a"),
        ("worker", ["violet", "storage"], "/b"),
    ]
    assert "/a:orchid" in outputs[0] and "violet" not in outputs[0]
    assert "/b:violet" in outputs[1] and "orchid" not in outputs[1]


@pytest.mark.parametrize(
    "arguments", [None, {"message": []}, {"message": "task", "agent_type": []}]
)
def test_invalid_native_arguments_report_skip_without_store(arguments, capsys):
    with patch.object(hook, "_connect") as connect:
        run(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "tool_input": arguments,
            }
        )
    connect.assert_not_called()
    out, err = capsys.readouterr()
    assert not out and "skip:" in err


def test_empty_store_leaves_spawn_unchanged(capsys):
    with (
        patch.object(hook, "_connect", return_value=MagicMock()),
        patch.object(hook, "_fetch_agent_context", return_value=[]),
    ):
        run(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "spawn_agent",
                "tool_input": {"message": "alpha task"},
            }
        )
    out, err = capsys.readouterr()
    assert not out and "no relevant memories" in err


def test_store_open_failure_is_visible_and_nonblocking(capsys):
    with patch.object(hook, "_connect", side_effect=OSError("unavailable")):
        run({"hook_event_name": "SubagentStart", "agent_type": "worker"})
    out, err = capsys.readouterr()
    assert not out and "store unavailable" in err


def test_query_failure_closes_connection_and_reports(capsys):
    conn = MagicMock()
    with (
        patch.object(hook, "_connect", return_value=conn),
        patch.object(hook, "_fetch_role_context", side_effect=RuntimeError("broken")),
    ):
        run({"hook_event_name": "SubagentStart", "agent_type": "worker"})
    out, err = capsys.readouterr()
    assert not out and "query failed" in err
    conn.close.assert_called_once()


@pytest.mark.parametrize(
    "event",
    [
        {"hook_event_name": "SubagentStart", "agent_type": []},
        {"hook_event_name": "SubagentStart", "agent_type": "worker", "prompt": ["bad"]},
        {"hook_event_name": "PreToolUse", "tool_name": "read_file"},
    ],
)
def test_invalid_or_unrelated_events_never_open_store(event, capsys):
    with patch.object(hook, "_connect") as connect:
        run(event)
    connect.assert_not_called()
    assert not capsys.readouterr().out


def test_opaque_collaboration_input_is_never_rewritten(capsys):
    arguments = {
        "message": "gAAAAopaque-native-payload",
        "agent_type": "default",
        "fork_turns": "none",
    }
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "collaborationspawn_agent",
        "tool_input": arguments,
    }
    with patch.object(hook, "_connect") as connect:
        run(event)
    assert not capsys.readouterr().out
    assert arguments["message"] == "gAAAAopaque-native-payload"
    connect.assert_not_called()
