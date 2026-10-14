"""mcp_server/hooks/session_start_status.py: what the user sees at session start.

Claude Code shows a SessionStart hook's ``systemMessage`` to the user and its
plain stdout only to Claude, so the status travels as one JSON object.

source: ADR-1104
"""

from __future__ import annotations

import json

import pytest

from mcp_server.hooks import session_start_status as status


def _emitted(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def test_context_and_status_leave_as_one_json_object(capsys):
    def main() -> str:
        print("## Cortex memories")
        return status.ready(
            "SQLite memory at ~/m.db", 3, {"CORTEX_SEMANTIC_SEARCH": "ready"}
        )

    status.run_and_report(main)
    out = _emitted(capsys)
    assert out["systemMessage"] == (
        "Cortex ready: SQLite memory at ~/m.db, 3 memories; semantic search on."
    )
    assert out["hookSpecificOutput"] == {
        "hookEventName": "SessionStart",
        "additionalContext": "## Cortex memories\n",
    }


def test_a_crash_is_shown_as_not_ready_and_still_raised(capsys):
    def main() -> str:
        raise RuntimeError("store schema is newer than this Cortex")

    with pytest.raises(RuntimeError):
        status.run_and_report(main)
    assert _emitted(capsys)["systemMessage"] == (
        "Cortex not ready: RuntimeError: store schema is newer than this Cortex"
    )


@pytest.mark.parametrize(
    ("environ", "clause"),
    [
        ({"CORTEX_SEMANTIC_SEARCH": "ready"}, "semantic search on"),
        (
            {"CORTEX_SEMANTIC_SEARCH": "installing"},
            "semantic search is installing in the background, "
            "keyword recall until it finishes",
        ),
        (
            {"CORTEX_SEMANTIC_SEARCH": "failed",
             "CORTEX_SEMANTIC_SEARCH_DETAIL": "no wheel"},
            "keyword recall only, semantic search install failed: no wheel",
        ),
        (
            {"CORTEX_SEMANTIC_SEARCH": "off",
             "CORTEX_SEMANTIC_SEARCH_DETAIL": "opt-out"},
            "keyword recall only, semantic search not installed: opt-out",
        ),
        (
            {"CORTEX_EMBEDDING_ZERO_DOWNLOAD": "1"},
            "keyword recall only, semantic search not installed: "
            "CORTEX_EMBEDDING_ZERO_DOWNLOAD is set",
        ),
    ],
)  # fmt: skip
def test_the_status_says_how_recall_ranks(environ, clause):
    assert status.semantic_clause(environ) == clause


def test_one_memory_is_singular():
    message = status.ready(
        "PostgreSQL memory store", 1, {"CORTEX_SEMANTIC_SEARCH": "ready"}
    )
    assert ", 1 memory;" in message


def test_home_relative(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert status.home_relative(str(tmp_path / ".claude" / "m.db")) == "~/.claude/m.db"
    assert status.home_relative("/elsewhere/m.db") == "/elsewhere/m.db"
