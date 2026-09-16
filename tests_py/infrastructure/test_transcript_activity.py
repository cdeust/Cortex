"""A session's tool calls come from its transcript, in order (issue #591).

The SessionEnd payload carries no `tools_used` and no `turn_count`, so every
session entry was written with `toolsUsed: []` and procedural mining never had
an input. The transcript carries both.

source: ADR-1072
"""

from __future__ import annotations

import json

from mcp_server.infrastructure.transcript_activity import (
    MAX_TOOL_SEQUENCE,
    transcript_activity,
)


def _assistant(*tools: str) -> dict:
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": name, "input": {}} for name in tools
            ]
        },
    }


def _write(path, records) -> str:
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    return str(path)


def test_order_and_repetition_are_preserved(tmp_path) -> None:
    transcript = _write(
        tmp_path / "s.jsonl",
        [
            {"type": "user", "message": {"content": "fix it"}},
            _assistant("Read", "Read"),
            {"type": "user", "message": {"content": "now test"}},
            _assistant("Edit"),
            _assistant("Bash", "Read"),
        ],
    )

    activity = transcript_activity(transcript)

    assert activity["tool_sequence"] == ["Read", "Read", "Edit", "Bash", "Read"]
    assert activity["turn_count"] == 3


def test_a_session_without_tools_reports_its_turns(tmp_path) -> None:
    transcript = _write(
        tmp_path / "s.jsonl",
        [
            {"type": "user", "message": {"content": "hello"}},
            {"type": "assistant", "message": {"content": "hi"}},
        ],
    )

    activity = transcript_activity(transcript)

    assert activity["tool_sequence"] == []
    assert activity["turn_count"] == 1


def test_a_malformed_line_does_not_lose_the_rest(tmp_path) -> None:
    path = tmp_path / "s.jsonl"
    path.write_text(
        json.dumps(_assistant("Read"))
        + "\n"
        + '{"type": "assistant", broken\n'
        + json.dumps(_assistant("Bash"))
        + "\n",
        encoding="utf-8",
    )

    assert transcript_activity(str(path))["tool_sequence"] == ["Read", "Bash"]


def test_a_missing_transcript_is_empty(tmp_path) -> None:
    assert transcript_activity(None) == {"tool_sequence": [], "turn_count": 0}
    assert transcript_activity(tmp_path / "absent.jsonl") == {
        "tool_sequence": [],
        "turn_count": 0,
    }


def test_the_sequence_is_capped(tmp_path) -> None:
    transcript = _write(
        tmp_path / "s.jsonl", [_assistant(*(["Bash"] * (MAX_TOOL_SEQUENCE + 50)))]
    )

    activity = transcript_activity(transcript)

    assert len(activity["tool_sequence"]) == MAX_TOOL_SEQUENCE
    assert activity["turn_count"] == 1
