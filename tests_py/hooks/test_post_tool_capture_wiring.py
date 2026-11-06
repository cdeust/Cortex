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


def test_a_raising_dispatch_is_logged_and_its_artifact_removed(
    artifacts, monkeypatch, capsys
):
    def boom(*args):
        raise RuntimeError("worker unreachable")

    monkeypatch.setattr(hook, "_store_memory", boom)

    hook.process_event(_event(_BIG))

    err = capsys.readouterr().err
    assert "capture failed (non-fatal): worker unreachable" in err
    assert "undelivered capture: artifact " in err
    assert " removed" in err
    assert list(artifacts.rglob("*.md")) == []


def test_a_removal_failure_is_logged(artifacts, monkeypatch, capsys):
    def refuse(path):
        raise PermissionError("read-only")

    monkeypatch.setattr(hook, "_store_memory", lambda *args: False)
    monkeypatch.setattr(artifact_store, "discard_created_artifact", refuse)

    hook.process_event(_event(_BIG))

    assert "could not be removed: read-only" in capsys.readouterr().err


@pytest.mark.parametrize("handed_over", [True, False])
def test_store_memory_reports_whether_dispatch_took_the_payload(
    monkeypatch, handed_over
):
    payloads: list[dict] = []

    def dispatch(payload):
        payloads.append(payload)
        return handed_over

    monkeypatch.setattr(capture_dispatch, "dispatch", dispatch)

    assert hook._store_memory("Bash", "body", ["t"], "/tmp/project") is handed_over
    assert payloads[0]["directory"] == "/tmp/project"
