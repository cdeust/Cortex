"""What process_event hands on, and what it logs, around the artifact (issue #737).

The capture path reads the event, builds the memory, hands it to dispatch and
removes an artifact its undelivered capture created. These tests pin each value
it passes along and each line it logs, so the mutation gate (ADR-1122) can judge
the functions #737 changed.
"""

from __future__ import annotations

import pytest

import mcp_server.hooks.capture_dispatch as capture_dispatch
import mcp_server.hooks.post_tool_capture as hook
import mcp_server.infrastructure.artifact_store as artifact_store
from mcp_server.core.gist_extraction import GIST_BUDGET


@pytest.fixture
def artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_store, "ARTIFACTS_DIR", tmp_path / "artifacts")
    return tmp_path / "artifacts"


@pytest.fixture
def stored(monkeypatch):
    calls: list[dict] = []

    def record(tool_name, content, tags, cwd):
        calls.append({"tool": tool_name, "content": content, "tags": tags, "cwd": cwd})
        return True

    monkeypatch.setattr(hook, "_store_memory", record)
    return calls


def _event(stdout: str, **overrides) -> dict:
    event = {
        "tool_name": "Bash",
        "tool_input": {"command": "run something"},
        "cwd": "/tmp/project",
        "tool_response": {"stdout": stdout, "stderr": ""},
    }
    event.update(overrides)
    return {k: v for k, v in event.items() if v is not None}


_SMALL = "build finished with enough characters to pass the floor of fifty"
_BIG = "\n".join(f"line-{i} build output padding" for i in range(2000))


def test_the_event_fields_reach_the_stored_memory(artifacts, stored):
    hook.process_event(_event(_SMALL))

    [call] = stored
    assert call["tool"] == "Bash"
    assert call["cwd"] == "/tmp/project"
    assert call["tags"][:2] == ["auto-captured", "tool:bash"]
    assert call["content"].startswith("# Tool: Bash")
    assert "**Command:** `run something`" in call["content"]


def test_an_event_without_cwd_stores_an_empty_directory(artifacts, stored):
    event = _event(_SMALL)
    del event["cwd"]

    hook.process_event(event)

    assert stored[0]["cwd"] == ""


def test_an_event_without_tool_name_is_skipped_as_an_empty_name(stored, capsys):
    event = _event(_SMALL)
    del event["tool_name"]

    hook.process_event(event)

    assert stored == []
    assert "skip : low_value_tool:\n" in capsys.readouterr().err


def test_a_short_output_is_skipped_with_its_reason(stored, capsys):
    hook.process_event(_event("too short"))

    assert stored == []
    assert "skip Bash: output_too_short" in capsys.readouterr().err


def test_the_pointer_names_the_artifact_and_its_length(artifacts, stored):
    hook.process_event(_event(_BIG))

    [path] = list(artifacts.rglob("*.md"))
    size = len(path.read_text(encoding="utf-8"))
    assert f"`{path}` ({size} chars full output)" in stored[0]["content"]


def test_an_artifact_write_failure_is_logged(stored, monkeypatch, capsys):
    def boom(content, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(artifact_store, "write_artifact", boom)
    assert len(_BIG) > GIST_BUDGET

    hook.process_event(_event(_BIG))

    err = capsys.readouterr().err
    assert "artifact write failed (non-fatal, full output kept): disk full" in err


def test_a_raising_dispatch_is_logged_and_its_artifact_kept(
    artifacts, monkeypatch, capsys
):
    def boom(*args):
        raise RuntimeError("worker unreachable")

    monkeypatch.setattr(hook, "_store_memory", boom)

    hook.process_event(_event(_BIG))

    err = capsys.readouterr().err
    assert "capture failed (non-fatal): worker unreachable" in err
    assert "undelivered capture" not in err
    assert len(list(artifacts.rglob("*.md"))) == 1


def test_a_declined_capture_logs_the_removed_artifact(artifacts, monkeypatch, capsys):
    monkeypatch.setattr(hook, "_store_memory", lambda *args: False)

    hook.process_event(_event(_BIG))

    err = capsys.readouterr().err
    assert "undelivered capture: artifact " in err
    assert err.rstrip().endswith(" removed")


def test_a_removal_failure_is_logged(artifacts, monkeypatch, capsys):
    def refuse(path):
        raise PermissionError("read-only")

    monkeypatch.setattr(hook, "_store_memory", lambda *args: False)
    monkeypatch.setattr(artifact_store, "discard_created_artifact", refuse)

    hook.process_event(_event(_BIG))

    assert "could not be removed: read-only" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("handoff", "handed_over", "queued"),
    [
        (capture_dispatch.Handoff.ADMITTED, True, True),
        (capture_dispatch.Handoff.UNCERTAIN, True, False),
        (capture_dispatch.Handoff.NOT_HANDED_OVER, False, False),
    ],
)
def test_store_memory_is_false_only_when_nothing_left_the_hook(
    monkeypatch, capsys, handoff, handed_over, queued
):
    payloads: list[dict] = []

    def dispatch(payload):
        payloads.append(payload)
        return handoff

    monkeypatch.setattr(capture_dispatch, "dispatch", dispatch)

    assert hook._store_memory("Bash", "body", ["t"], "/tmp/project") is handed_over
    assert payloads[0]["directory"] == "/tmp/project"
    logged = "queued Bash for capture (persistence pending)" in capsys.readouterr().err
    assert logged is queued


def test_an_uncertain_handoff_keeps_the_artifact(artifacts, monkeypatch):
    monkeypatch.setattr(
        capture_dispatch, "dispatch", lambda payload: capture_dispatch.Handoff.UNCERTAIN
    )

    hook.process_event(_event(_BIG))

    assert len(list(artifacts.rglob("*.md"))) == 1


def test_a_spooled_capture_whose_drainer_fails_keeps_its_artifact(
    artifacts, tmp_path, monkeypatch
):
    """Review of PR #907: the spool file is durable, so its pointer must hold."""
    from mcp_server.infrastructure import capture_spool

    monkeypatch.setattr(capture_dispatch, "CLAUDE_DIR", tmp_path / "claude")
    monkeypatch.setattr(capture_dispatch, "is_supported", lambda: False)

    def no_spawn(log_path):
        raise OSError("no spawn")

    monkeypatch.setattr(capture_dispatch, "spawn_drainer", no_spawn)

    hook.process_event(_event(_BIG))

    spool = capture_spool.spool_directory(tmp_path / "claude")
    assert len(capture_spool.pending(spool)) == 1
    assert len(list(artifacts.rglob("*.md"))) == 1
