"""Malformed and hostile rollouts: what the Codex reader skips, and what it keeps.

A rollout is data written by another program; every level of a record can hold
anything. These pin that a bad line, record, block or file is skipped without
losing the good ones around it (issue #726).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_server.infrastructure.codex_history import (
    discover_codex_conversations,
    parse_rollout_conversation,
)

_META = {
    "timestamp": "2026-09-01T00:00:00Z",
    "type": "session_meta",
    "payload": {"cwd": "/work/repo", "thread_source": "user"},
}
_ASSISTANT = {
    "timestamp": "2026-09-01T00:00:09Z",
    "type": "response_item",
    "payload": {"type": "message", "role": "assistant", "content": []},
}


def _event(payload) -> dict:
    return {
        "timestamp": "2026-09-01T00:00:01Z",
        "type": "event_msg",
        "payload": payload,
    }


def _prompt(text) -> dict:
    return _event({"type": "user_message", "message": text})


def _item(content) -> dict:
    item = {"type": "UserMessage", "id": "u", "content": content}
    return _event({"type": "item_completed", "item": item})


def _lines(path: Path, lines: list) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = [x if isinstance(x, bytes) else json.dumps(x).encode() for x in lines]
    path.write_bytes(b"\n".join(raw) + b"\n")
    return path


def _parse(tmp_path: Path, records: list) -> dict | None:
    return parse_rollout_conversation(_lines(tmp_path / "rollout-x.jsonl", records))


def test_a_malformed_line_does_not_end_the_read(tmp_path):
    record = _parse(tmp_path, [_META, b"{not json", _prompt("kept"), _ASSISTANT])
    assert record["firstMessage"] == "kept"


def test_a_line_that_is_not_utf8_is_skipped(tmp_path):
    bad = (
        b'{"type": "event_msg", "payload": {"type": "user_message", "message": "\xff"}}'
    )
    record = _parse(tmp_path, [_META, bad, _prompt("kept"), _ASSISTANT])
    assert (record["userCount"], record["firstMessage"]) == (1, "kept")


def test_an_empty_file_is_none(tmp_path):
    path = tmp_path / "rollout-empty.jsonl"
    path.write_bytes(b"")
    assert parse_rollout_conversation(path) is None


def test_a_first_record_that_is_not_session_meta_is_none(tmp_path):
    impostor = {"type": "turn_context", "payload": {"cwd": "/work/repo"}}
    assert _parse(tmp_path, [impostor, _prompt("p"), _ASSISTANT]) is None


@pytest.mark.parametrize("payload", [["/work/repo"], "x", None])
def test_a_session_meta_payload_that_is_not_an_object_is_none(tmp_path, payload):
    meta = {"type": "session_meta", "payload": payload}
    assert _parse(tmp_path, [meta, _prompt("p"), _ASSISTANT]) is None


def test_a_cwd_that_is_not_a_string_is_none(tmp_path):
    meta = {"type": "session_meta", "payload": {"cwd": 42}}
    assert _parse(tmp_path, [meta, _prompt("p"), _ASSISTANT]) is None


def test_non_string_and_non_object_payloads_are_not_prompts(tmp_path):
    records = [_META, _prompt(123), _event("x"), _prompt("kept"), _ASSISTANT]
    record = _parse(tmp_path, records)
    assert (record["userCount"], record["allText"]) == (1, "kept")


def test_paginated_prompt_joins_text_blocks_and_skips_the_rest(tmp_path):
    content = [
        {"type": "text", "text": "first"},
        "not a block",
        {"type": "text", "text": None},
        {"type": "image", "url": "file:///x.png"},
        {"type": "text", "text": "second"},
    ]
    record = _parse(tmp_path, [_META, _item(content), _ASSISTANT])
    assert record["firstMessage"] == "first second"


def test_an_unreadable_rollout_is_reported_and_the_scan_goes_on(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    day = tmp_path / "sessions" / "2026" / "09" / "01"
    (day / "rollout-a.jsonl").mkdir(parents=True)  # opening it raises an OSError
    _lines(day / "rollout-b.jsonl", [_META, _prompt("kept"), _ASSISTANT])

    found = discover_codex_conversations()

    assert [r["firstMessage"] for r in found] == ["kept"]
    captured = capsys.readouterr()
    assert "Failed to read rollout" in captured.err
    assert "rollout-a.jsonl" in captured.err
    assert captured.out == ""


def test_a_timestamp_that_is_not_a_string_is_skipped(tmp_path):
    late = {**_ASSISTANT, "timestamp": "2026-09-01T00:05:00Z"}
    odd = {**_prompt("kept"), "timestamp": 1}
    early = {**_ASSISTANT, "timestamp": "2026-08-31T23:59:00Z"}
    record = _parse(tmp_path, [_META, late, odd, early])
    assert record["startedAt"] == "2026-08-31T23:59:00Z"
    assert record["endedAt"] == "2026-09-01T00:05:00Z"
    assert record["userCount"] == 1


def test_no_string_timestamp_gives_no_time_span(tmp_path):
    meta = {"type": "session_meta", "payload": {"cwd": "/work/repo"}}
    record = _parse(tmp_path, [meta, {**_prompt("kept"), "timestamp": None}])
    assert (record["startedAt"], record["endedAt"], record["duration"]) == (
        None,
        None,
        None,
    )


def test_a_too_deeply_nested_line_skips_its_rollout_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    day = tmp_path / "sessions" / "2026" / "09" / "01"
    deep = b"[" * 200_000 + b"]" * 200_000  # source: past CPython's recursion limit
    _lines(day / "rollout-a.jsonl", [_META, deep, _prompt("lost"), _ASSISTANT])
    _lines(day / "rollout-b.jsonl", [_META, _prompt("kept"), _ASSISTANT])

    found = discover_codex_conversations()

    assert [r["firstMessage"] for r in found] == ["kept"]
    assert "rollout-a.jsonl" in capsys.readouterr().err
