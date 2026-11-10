"""PRIVACY.md says what PostToolUse auto-capture copies; the hook is held to it.

Each test reads the claim from the PRIVACY.md paragraph and drives the real
``process_event`` with the matching event, so the text and the hook cannot
drift apart silently (issue #737, slice 4).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import mcp_server.hooks.post_tool_capture as hook
import mcp_server.infrastructure.artifact_store as artifact_store
from mcp_server.core.gist_extraction import GIST_BUDGET
from mcp_server.hooks._capture_mode import HIGH_VALUE_TOOLS

_PRIVACY = Path(__file__).resolve().parents[2] / "PRIVACY.md"
_MARKER = "Tool calls, through the Claude Code plugin's PostToolUse auto-capture"


def _paragraph() -> str:
    text = _PRIVACY.read_text(encoding="utf-8")
    start = text.index(_MARKER)
    return " ".join(text[start : text.index("\n## ", start)].split())


def _tools_of(item_start: str) -> set[str]:
    """Tool names listed at the head of the bullet that starts with ``item_start``."""
    line = next(
        part for part in _paragraph().split(" - ") if part.startswith(item_start)
    )
    head = line.split(":", 1)[0]
    return set(re.findall(r"[A-Z][A-Za-z]+", head))


def _number_before(phrase: str) -> int:
    match = re.search(r"(\d+) " + re.escape(phrase), _paragraph())
    assert match, phrase
    return int(match.group(1))


@pytest.fixture
def captured(monkeypatch, tmp_path):
    monkeypatch.setattr(artifact_store, "ARTIFACTS_DIR", tmp_path / "artifacts")
    monkeypatch.setattr(hook, "_maybe_run_cascade", lambda event: None)
    monkeypatch.delenv("CORTEX_CAPTURE_MODE", raising=False)
    calls: list[str] = []

    def fake_store(tool_name, content, tags, cwd):
        calls.append(content)
        return True

    monkeypatch.setattr(hook, "_store_memory", fake_store)
    return calls


def _event(tool: str, tool_input: dict, response: str) -> dict:
    return {
        "tool_name": tool,
        "tool_input": tool_input,
        "cwd": "/home/someone/client-project",
        "tool_response": response,
    }


def test_the_listed_tool_groups_are_the_hooks_own():
    assert _tools_of("Edit, Write") == set(HIGH_VALUE_TOOLS)
    assert _tools_of("Read, NotebookRead") == hook._LIGHT_VALUE_TOOLS
    assert _tools_of("WebFetch and WebSearch") == hook._CONDITIONAL_TOOLS


def test_the_stated_limits_are_the_hooks_own(captured):
    assert _number_before("characters long, plus") == hook._MIN_OUTPUT_LENGTH
    assert _number_before("characters is stored as a short gist") == GIST_BUDGET
    command = "grep -n 'Alice Martin' clients.csv " + "x" * 400
    hook.process_event(_event("Bash", {"command": command}, "y" * 60))
    kept = _number_before("characters of the command line")
    assert f"`{command[:kept]}`" in captured[-1]
    assert command[: kept + 1] not in captured[-1]


def test_a_read_copies_the_path_and_not_the_contents(captured):
    contents = "Alice Martin, 12 rue des Lilas, diabetic\n" * 5
    hook.process_event(_event("Read", {"file_path": "/p/clients.csv"}, contents))
    assert "/p/clients.csv" in captured[-1]
    assert "Alice Martin" not in captured[-1]


def test_a_grep_pattern_made_of_names_is_copied(captured):
    hook.process_event(_event("Grep", {"pattern": "Alice Martin", "path": "/p"}, ""))
    assert "Alice Martin" in captured[-1]


def test_personal_data_in_a_response_is_stored_as_it_is(captured):
    response = "Alice Martin <alice@example.org> +33 6 12 34 56 78, diabetic"
    hook.process_event(_event("Bash", {"command": "cat notes"}, response))
    assert response in captured[-1]


def test_a_long_response_goes_to_an_artifact_and_the_row_keeps_a_gist(captured):
    response = "\n".join(f"Patient {i}: Alice Martin" for i in range(400))
    assert len(response) > GIST_BUDGET
    hook.process_event(_event("Bash", {"command": "cat patients"}, response))
    files = list(artifact_store.ARTIFACTS_DIR.rglob("*.md"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == response
    assert response not in captured[-1]
    assert str(files[0]) in captured[-1]
