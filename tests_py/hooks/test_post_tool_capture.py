"""Tests for the PostToolUse auto-capture hook gist + artifact wiring."""

from __future__ import annotations

import pytest

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


# ── Capture must not be decided by the captured content (issue #365) ───────


class TestNetworkToolCaptureIsContentIndependent:
    """WebFetch/WebSearch output is off-machine content.

    The predicate used to be `any(kw in output.lower() for kw in
    HIGH_VALUE_PATTERNS)`, which let a fetched page decide whether it was
    written to long-term memory by including one of those words — and
    hooks/session_start replays stored memories verbatim into later sessions.
    The rule is now a fixed length floor, identical for any payload.
    """

    LONG_WITH_KEYWORD = "x" * 60 + " decided to switch to the attacker's advice"
    LONG_WITHOUT_KEYWORD = "y" * 90
    TOO_SHORT = "z" * 10

    @pytest.mark.parametrize("tool", ["WebFetch", "WebSearch"])
    def test_same_verdict_regardless_of_keywords(self, tool):
        from mcp_server.hooks.post_tool_capture import _should_capture

        with_kw, _ = _should_capture(tool, {}, self.LONG_WITH_KEYWORD)
        without_kw, _ = _should_capture(tool, {}, self.LONG_WITHOUT_KEYWORD)
        assert with_kw == without_kw, (
            "the capture decision still depends on the fetched content — a page "
            "can select itself for persistence"
        )

    @pytest.mark.parametrize("tool", ["WebFetch", "WebSearch"])
    def test_reason_names_the_tool_not_a_keyword(self, tool):
        """The recorded reason must not echo attacker-chosen text."""
        from mcp_server.hooks.post_tool_capture import _should_capture

        ok, reason = _should_capture(tool, {}, self.LONG_WITH_KEYWORD)
        assert ok is True
        assert reason == f"network_tool:{tool}"
        assert "keyword" not in reason

    @pytest.mark.parametrize("tool", ["WebFetch", "WebSearch"])
    def test_length_floor_still_applies(self, tool):
        from mcp_server.hooks.post_tool_capture import _should_capture

        assert _should_capture(tool, {}, self.TOO_SHORT) == (
            False,
            "output_too_short",
        )

    def test_the_hook_reports_the_producing_tool_to_remember(self):
        """origin_tool must reach `remember`, or the gate cannot refuse.

        Asserts the payload contract rather than a downstream effect: this is
        the seam where the channel identity is handed over.
        """
        import inspect

        from mcp_server.hooks import post_tool_capture

        src = inspect.getsource(post_tool_capture._store_memory)
        assert '"origin_tool": tool_name' in src, (
            "_store_memory must pass origin_tool so handlers/remember can "
            "resolve the capture origin from the channel"
        )
