"""The query_methodology description matches what the hooks do (issue #710).

No hook calls ``query_methodology``, so the profile reaches a session only when
the model calls the tool. The description used to say the call was "MANDATORY
at session start", a promise nothing kept. These tests tie the description to
the hooks: adding a hook that injects the profile fails the first test until the
description says so.
"""

from __future__ import annotations

from pathlib import Path

from mcp_server.handlers.query_methodology import schema

_HOOKS_DIR = Path(__file__).resolve().parents[2] / "mcp_server" / "hooks"


def _hook_sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in _HOOKS_DIR.rglob("*.py")}


def test_no_hook_calls_query_methodology() -> None:
    callers = [
        name for name, text in _hook_sources().items() if "query_methodology" in text
    ]
    assert callers == [], (
        f"hooks now reference query_methodology ({callers}); update the tool "
        "description, which says no hook calls it"
    )


def test_description_does_not_promise_a_session_start_call() -> None:
    description = schema["description"]
    assert "MANDATORY" not in description
    assert "session start" not in description.lower()


def test_description_says_the_model_must_call_it() -> None:
    assert "No hook calls this tool" in schema["description"]
