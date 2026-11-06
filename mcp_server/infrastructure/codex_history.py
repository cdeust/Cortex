"""Conversation records from Codex rollouts, for the profile rebuild.

`rebuild_profiles` built every domain from `~/.claude/projects` only, and
`scanner_parse.extract_message_stats` reads top-level `user`/`assistant`
records, so a Codex rollout (`session_meta`, `response_item`, `event_msg`
records) parsed to zero messages and a Codex-only history created no domain
(issue #726). This reader turns one rollout into the same conversation record
`scanner_parse.build_conversation_record` assembles for a Claude transcript,
so the rest of the rebuild (grouping, profile assembly) is unchanged.

Where rollouts live: `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-*.jsonl`, with
`CODEX_HOME` defaulting to `~/.codex` when unset or empty.
source: openai/codex@e7f32cf, codex-rs/utils/home-dir/src/lib.rs
(`find_codex_home`) and codex-rs/rollout/src/lib.rs (`SESSIONS_SUBDIR`).

What is read:
- the project: `session_meta.payload.cwd`, through the same
  `cwd_to_project_id` that names a Claude project directory, so one
  repository worked on from both hosts lands in one project;
- typed prompts: `event_msg` `user_message` (legacy history) and `event_msg`
  `item_completed` whose item is a `UserMessage` (paginated history). Codex's
  own thread preview reads exactly these two shapes
  (codex-rs/rollout/src/list.rs, `event_msg_preview`). `response_item`
  messages with role `user` are not read: they also carry the injected
  `<environment_context>` and instruction blocks, which no user typed;
- assistant turns and the tool sequence: `transcript_rollout.rollout_activity`
  (ADR-1081), the reader SessionEnd already uses for the same file.

A rollout whose `session_meta.payload.thread_source` names anything but
`user` (subagent, guardian review, memory consolidation) is skipped, as the
Claude scan skips subagent transcripts; a rollout without the field (older
Codex) is a user thread. source: codex-rs/protocol/src/protocol.rs
(`ThreadSource`).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp_server.infrastructure.scanner_parse import (
    _MAX_USER_TEXT_CHARS,  # same prompt-text cap as the Claude reader, ADR-0596
    build_conversation_record,
)
from mcp_server.infrastructure.transcript_activity import MAX_TOOL_SEQUENCE
from mcp_server.infrastructure.transcript_rollout import rollout_activity
from mcp_server.shared.project_ids import cwd_to_project_id

_USER_THREAD_SOURCE = "user"


def codex_sessions_dir() -> Path:
    """`$CODEX_HOME/sessions`, `CODEX_HOME` defaulting to `~/.codex`."""
    home = os.environ.get("CODEX_HOME")
    root = Path(home).expanduser() if home else Path.home() / ".codex"
    return root / "sessions"


def _prompt_text(payload: dict) -> str | None:
    """The typed prompt an `event_msg` payload carries, or None."""
    if payload.get("type") == "user_message":
        message = payload.get("message")
        return message if isinstance(message, str) else None
    if payload.get("type") != "item_completed":
        return None
    item = payload.get("item")
    if not isinstance(item, dict) or item.get("type") != "UserMessage":
        return None
    content = item.get("content")
    if not isinstance(content, list):
        return None
    return " ".join(
        block["text"]
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    )


def _read_records(path: Path) -> list[dict]:
    """Every JSON-object line; a line that is not UTF-8 JSON is skipped, as a
    malformed line is (`json.loads` decodes bytes itself, RFC 8259 §8.1)."""
    records: list[dict] = []
    with path.open("rb") as stream:
        for line in stream:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def _session_meta(records: list[dict]) -> dict | None:
    first = records[0] if records else None
    if not first or first.get("type") != "session_meta":
        return None
    payload = first.get("payload")
    return payload if isinstance(payload, dict) else None


def _time_span(records: list[dict]) -> dict[str, str | None]:
    """First and last ISO timestamp. A `timestamp` that is not a string is
    skipped: comparing it with a string raised `TypeError` and aborted the
    whole rebuild, Claude profiles included (#881 review)."""
    stamps = [r["timestamp"] for r in records if isinstance(r.get("timestamp"), str)]
    return {
        "first_timestamp": min(stamps, default=None),
        "last_timestamp": max(stamps, default=None),
    }


def _prompts(records: list[dict]) -> list[str]:
    prompts: list[str] = []
    for record in records:
        payload = record.get("payload")
        if record.get("type") != "event_msg" or not isinstance(payload, dict):
            continue
        text = _prompt_text(payload)
        if text:
            prompts.append(text)
    return prompts


def _message_stats(prompts: list[str], path: Path) -> dict[str, Any]:
    """The `extract_message_stats` shape, read from a rollout."""
    activity = rollout_activity(path, MAX_TOOL_SEQUENCE)
    all_text = " ".join(prompts)[:_MAX_USER_TEXT_CHARS]
    return {
        "user_count": len(prompts),
        "assistant_count": activity["turn_count"],
        "tools_used": activity["tool_sequence"],
        "first_message": prompts[0] if prompts else None,
        "all_text": all_text or None,
    }


def parse_rollout_conversation(path: Path) -> dict[str, Any] | None:
    """One rollout as a conversation record, or None when it is not a user
    thread with a working directory and at least one message.

    precondition: `path` is a readable file. postcondition: the record has
    the keys `build_conversation_record` returns, `project` is
    `cwd_to_project_id(session_meta.cwd)`, `slug` is None (Codex has none)
    and `source` is `"codex"`.
    """
    records = _read_records(path)
    meta = _session_meta(records)
    if meta is None:
        return None
    thread_source = meta.get("thread_source")
    if thread_source not in (None, _USER_THREAD_SOURCE):
        return None
    cwd = meta.get("cwd")
    project = cwd_to_project_id(cwd if isinstance(cwd, str) else None)
    if not project:
        return None
    stats = _message_stats(_prompts(records), path)
    if stats["user_count"] + stats["assistant_count"] == 0:
        return None
    fields = {"slug": None, "cwd": cwd, **_time_span(records)}
    record = build_conversation_record(fields, stats, path, project)
    record["source"] = "codex"
    return record


def discover_codex_conversations() -> list[dict[str, Any]]:
    """Every user-thread rollout under `codex_sessions_dir()`, path order.

    A missing directory is an empty history. A rollout that cannot be read,
    or holds a line nested deeper than `json.loads` can recurse (it raises
    `RecursionError` here and in `rollout_activity`), is reported to stderr and
    skipped, as `scanner` does for a Claude transcript (#881 review).
    """
    root = codex_sessions_dir()
    if not root.is_dir():
        return []
    conversations: list[dict[str, Any]] = []
    for path in sorted(root.rglob("rollout-*.jsonl")):
        try:
            record = parse_rollout_conversation(path)
        except (OSError, RecursionError) as exc:  # a too-deeply nested line
            print(
                f"[methodology-agent] Failed to read rollout {path}: {exc}",
                file=sys.stderr,
            )
            continue
        if record:
            conversations.append(record)
    return conversations
