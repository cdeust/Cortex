"""Read a Codex rollout transcript the way `transcript_activity` reads a
Claude Code one: an ordered tool-call sequence and an assistant turn count.

A rollout is JSONL. Its first record is `{"type": "session_meta", ...}`,
which `transcript_activity` uses to route here instead of to the Claude
reader. The records this reads are `{"type": "response_item", "payload":
{"type": "function_call" | "custom_tool_call", "name": ..., ...}}` for tool
calls, in file order, and `{"type": "response_item", "payload": {"type":
"message", "role": "assistant", ...}}` for turns. Every other record type
(`event_msg`, `reasoning`, `agent_message`, `compacted`, the `_output`
twins, and `response_item` `message` records with role `user` or
`developer`) is read past, not into: this module answers "what tools ran,
how many turns", the same question `transcript_activity` already answers
for Claude, not "what was said".

The shell tool surfaces here as a single `custom_tool_call` named `exec`
per invocation, whatever JavaScript program its `input` carries — that
script is not descended into; a `tools.exec_command(...)` call inside it is
not a separate tool call for this reader's purpose, matching how Claude's
`Bash` tool is one call regardless of the command it runs.

source: ADR-1081"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_TOOL_CALL_PAYLOAD_TYPES = frozenset({"function_call", "custom_tool_call"})


def _tool_call_name(payload: dict) -> str | None:
    if payload.get("type") not in _TOOL_CALL_PAYLOAD_TYPES:
        return None
    name = payload.get("name")
    return name if isinstance(name, str) and name else None


def _is_assistant_turn(payload: dict) -> bool:
    return payload.get("type") == "message" and payload.get("role") == "assistant"


def rollout_activity(path: Path, max_tool_sequence: int) -> dict[str, Any]:
    """Return {"tool_sequence": [...], "turn_count": n} for a rollout.

    precondition: `path` names a file already confirmed to start with a
    `session_meta` record — this function itself trusts nothing about the
    rest of it. postcondition: `tool_sequence` holds each `function_call`
    and `custom_tool_call` name in file order, repetitions included,
    capped at `max_tool_sequence`; `turn_count` counts `response_item`
    `message` records whose `role` is `"assistant"`. A malformed line, a
    non-object record, or a `response_item` whose `payload` is not an
    object is skipped, matching the Claude reader's degrade — an
    unreadable file yields the empty result rather than raising, since
    this runs inside the SessionEnd hook.
    """
    empty: dict[str, Any] = {"tool_sequence": [], "turn_count": 0}
    sequence: list[str] = []
    turns = 0
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("type") != "response_item":
                    continue
                payload = record.get("payload")
                if not isinstance(payload, dict):
                    continue
                if _is_assistant_turn(payload):
                    turns += 1
                    continue
                name = _tool_call_name(payload)
                if name and len(sequence) < max_tool_sequence:
                    sequence.append(name)
    except OSError:
        return empty
    return {"tool_sequence": sequence[:max_tool_sequence], "turn_count": turns}
