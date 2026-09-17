"""A Codex rollout is read for its tool sequence and turn count the same way
a Claude Code transcript is — different record shapes, same two-field
answer.

source: ADR-1081
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_server.infrastructure.transcript_activity import transcript_activity

FIXTURE = Path(__file__).parent / "fixtures" / "codex_rollout_excerpt.jsonl"


def test_a_rollout_yields_its_tool_sequence_and_turn_count() -> None:
    activity = transcript_activity(FIXTURE)

    assert activity["tool_sequence"] == ["exec", "exec", "send_message", "exec"]
    assert activity["turn_count"] == 2


def test_a_rollout_without_a_session_meta_falls_to_the_claude_reader(
    tmp_path,
) -> None:
    """No `session_meta` record means this is not recognisable as a rollout
    at all; it falls to the Claude reader, which finds no `"assistant"`
    record shaped the way it expects and returns the empty result."""
    path = tmp_path / "not-a-rollout.jsonl"
    path.write_text(
        json.dumps(
            {
                "type": "response_item",
                "payload": {"type": "function_call", "name": "exec"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert transcript_activity(path) == {"tool_sequence": [], "turn_count": 0}


def test_an_empty_rollout_style_file_is_not_a_crash(tmp_path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")

    assert transcript_activity(path) == {"tool_sequence": [], "turn_count": 0}
