"""Tests for the PostToolUse auto-capture hook gist + artifact wiring."""

from __future__ import annotations

import mcp_server.hooks.post_tool_capture as hook
import mcp_server.infrastructure.artifact_store as artifact_store
from mcp_server.core.gist_extraction import GIST_BUDGET


def _capture_store(monkeypatch):
    """Replace _store_memory with a recorder; return the captured-calls list."""
    captured: list[dict] = []

    def fake_store(tool_name, content, tags, cwd):
        captured.append({"tool": tool_name, "content": content, "tags": tags})

    monkeypatch.setattr(hook, "_store_memory", fake_store)
    return captured


def _bash_event(stdout: str) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": "run something"},
        "cwd": "/tmp/project",
        "tool_response": {"stdout": stdout, "stderr": ""},
    }


def test_oversized_output_produces_gist_and_artifact_pointer(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_store, "ARTIFACTS_DIR", tmp_path / "artifacts")
    captured = _capture_store(monkeypatch)

    big_stdout = "\n".join(f"build log line {i} padding" for i in range(2000))
    hook.process_event(_bash_event(big_stdout))

    assert len(captured) == 1
    content = captured[0]["content"]
    # Body carries a pointer line and an elision marker (the gist).
    assert "**Artifact:**" in content
    assert "[gist:" in content
    # Body is bounded — not the full multi-KB dump.
    assert len(content) < len(big_stdout)


def test_artifact_file_holds_full_raw_output(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_store, "ARTIFACTS_DIR", tmp_path / "artifacts")
    _capture_store(monkeypatch)

    big_stdout = "\n".join(f"unique-token-{i} build output" for i in range(2000))
    hook.process_event(_bash_event(big_stdout))

    # Exactly one artifact file written; it holds the FULL raw normalized
    # output (every unique token present).
    files = list((tmp_path / "artifacts").rglob("*.md"))
    assert len(files) == 1
    raw = files[0].read_text(encoding="utf-8")
    assert "unique-token-0" in raw
    assert "unique-token-1999" in raw


def test_small_output_stored_full_no_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(artifact_store, "ARTIFACTS_DIR", tmp_path / "artifacts")
    captured = _capture_store(monkeypatch)

    small_stdout = (
        "short build output that is comfortably over the\n"
        "50-char minimum capture floor\nall good"
    )
    hook.process_event(_bash_event(small_stdout))

    assert len(captured) == 1
    content = captured[0]["content"]
    assert "**Artifact:**" not in content
    assert small_stdout in content
    assert not (tmp_path / "artifacts").exists()


def test_artifact_store_failure_falls_back_to_full_content(tmp_path, monkeypatch):
    captured = _capture_store(monkeypatch)

    def boom(content, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(artifact_store, "store_artifact", boom)

    big_stdout = "\n".join(f"line {i} content padding here" for i in range(2000))
    assert len(big_stdout) > GIST_BUDGET
    hook.process_event(_bash_event(big_stdout))

    assert len(captured) == 1
    content = captured[0]["content"]
    # Fallback: full output kept, no pointer line.
    assert "**Artifact:**" not in content
    assert "line 1999 content padding here" in content
