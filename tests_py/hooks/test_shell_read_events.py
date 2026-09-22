"""Native stdout is not execution metadata; source: ADR-1086 capture."""

from unittest.mock import patch

import pytest

from mcp_server.hooks import preemptive_context as hook
from mcp_server.hooks.shell_read_events import completed_shell_read


@pytest.fixture
def event(tmp_path):
    (tmp_path / "a.py").write_text("hello")
    return {
        "session_id": "thread-a",
        "hook_event_name": "PostToolUse",
        "cwd": str(tmp_path),
        "tool_name": "Bash",
        "tool_input": {"command": "cat a.py"},
        "tool_response": "hello\n",
    }


@pytest.mark.parametrize(
    "output", ["hello\n", '{"exit_code":1}', "Process exited with code 1\n", ""]
)
def test_native_stdout_is_only_a_completed_access_cue(event, tmp_path, output):
    event["tool_response"] = output
    assert completed_shell_read(event, str(tmp_path), tmp_path / "pending") == (
        [str(tmp_path / "a.py")],
        str(tmp_path),
    )


def test_native_failed_missing_file_produces_no_cue(event, tmp_path):
    event["tool_input"] = {"command": "cat missing.py"}
    event["tool_response"] = "cat: missing.py: No such file or directory\n"
    assert completed_shell_read(event, str(tmp_path), tmp_path / "pending")[0] == []


@pytest.mark.parametrize(
    "response", [{"exit_code": 1}, {"exit_code": 0, "is_error": True}, {}]
)
def test_structured_failure_or_unknown_completion_does_not_prime(
    event, tmp_path, response
):
    event["tool_response"] = response
    assert completed_shell_read(event, str(tmp_path), tmp_path / "pending")[0] == []


def test_raw_shell_workdir_and_normalized_bash_are_not_double_resolved(event, tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.py").write_text("hello")
    event.update(
        tool_name="exec_command",
        tool_input={"cmd": "cat b.py", "workdir": "sub"},
        tool_response={"exit_code": 0},
    )
    assert completed_shell_read(event, str(tmp_path), tmp_path / "pending")[0] == [
        str(sub / "b.py")
    ]
    event.update(
        tool_name="Bash",
        cwd=str(sub),
        tool_input={"command": "cat b.py", "workdir": "sub"},
    )
    assert completed_shell_read(event, str(tmp_path), tmp_path / "pending")[0] == [
        str(sub / "b.py")
    ]


def test_async_completion_is_correlated_to_its_thread_and_consumed_once(
    event, tmp_path
):
    pending = tmp_path / "pending"
    event["tool_response"] = {"session_id": 17, "exit_code": None}
    assert completed_shell_read(event, "/origin", pending)[0] == []
    poll = {
        **event,
        "tool_name": "write_stdin",
        "tool_input": {"session_id": 17},
        "tool_response": {"exit_code": 0},
    }
    assert (
        completed_shell_read({**poll, "session_id": "other-thread"}, "/wrong", pending)[
            0
        ]
        == []
    )
    assert completed_shell_read(poll, "/wrong", pending) == (
        [str(tmp_path / "a.py")],
        "/origin",
    )
    assert completed_shell_read(poll, "/wrong", pending)[0] == []


def test_interactive_input_invalidates_pending_read(event, tmp_path):
    pending = tmp_path / "pending"
    event["tool_response"] = {"session_id": 17}
    completed_shell_read(event, "/origin", pending)
    poll = {
        **event,
        "tool_name": "write_stdin",
        "tool_input": {"session_id": 17, "chars": "x"},
    }
    assert completed_shell_read(poll, "/origin", pending)[0] == []
    poll.update(tool_input={"session_id": 17}, tool_response={"exit_code": 0})
    assert completed_shell_read(poll, "/origin", pending)[0] == []


def test_multi_file_call_primes_once_and_cooldown_is_project_scoped(
    event, tmp_path, monkeypatch
):
    (tmp_path / "b.py").write_text("hello")
    event["tool_input"] = {"command": "cat a.py b.py"}
    monkeypatch.setattr(hook, "_COOLDOWN_FILE", tmp_path / "cooldown.json")
    monkeypatch.delenv("CLAUDE_PROJECT_ROOT", raising=False)
    with patch.object(hook, "_prime_file_memories", return_value=1) as prime:
        hook.process_event(event)
        hook.process_event(event)
        assert prime.call_count == 1
        prime.assert_called_once_with(
            [str(tmp_path / "a.py"), str(tmp_path / "b.py")], str(tmp_path)
        )
        monkeypatch.setenv("CLAUDE_PROJECT_ROOT", "/other")
        hook.process_event(event)
        assert prime.call_count == 2


def test_symlink_and_relative_paths_share_cooldown(event, tmp_path, monkeypatch):
    (tmp_path / "alias.py").symlink_to(tmp_path / "a.py")
    monkeypatch.setattr(hook, "_COOLDOWN_FILE", tmp_path / "cooldown.json")
    monkeypatch.delenv("CLAUDE_PROJECT_ROOT", raising=False)
    with patch.object(hook, "_prime_file_memories", return_value=1) as prime:
        hook.process_event(event)
        event["tool_input"] = {"command": "cat ./alias.py"}
        hook.process_event(event)
        assert prime.call_count == 1
