"""What a session actually did, read from its transcript.

The SessionEnd payload carries `session_id`, `transcript_path` and `cwd`; it
carries neither the tools the session used nor its turn count, so
`hooks/session_lifecycle.py` wrote every session entry with `toolsUsed: []`
and `turnCount: 0` and procedural mining never had an input (issue #591).

The transcript has both. This reads it as a stream, keeping the tool calls in
the order they were made, repetitions included, because `core.procedural_memory`
mines contiguous subsequences: a deduplicated set would describe a sequence
nobody performed.

Two transcript shapes exist. Claude Code writes `{"type": "assistant", ...}`
records read below; Codex writes a rollout whose first record is
`{"type": "session_meta", ...}`, read by `transcript_rollout.rollout_activity`.
`transcript_activity` peeks the first record to choose between them — nothing
about the file extension or the caller's host distinguishes the two, only the
first line does. Neither reader touches a transcript's user-role prompt text
(the Codex rollout's `AGENTS.md` and `<environment_context>` blocks included);
a future caller that needs prompt content is a second concern and belongs in
a reader of its own, not grafted onto this one.

source: ADR-1072"""

from __future__ import annotations

import json
from os import PathLike
from pathlib import Path
from typing import Any

from mcp_server.infrastructure.transcript_rollout import rollout_activity

# A session's tool calls, capped so one long session cannot dominate the
# session log.
# source: measured 2026-09-16 over the 374 transcripts under
# ~/.claude/projects, where the largest carried 539 tool calls and the
# median non-empty one 34; the decision is recorded in ADR number 1072.
MAX_TOOL_SEQUENCE = 2000


def _message_content(record: dict) -> Any:
    """The record's message content, or None when the record is not shaped
    the way a transcript record is. Nothing here trusts a field's type:
    every level of a hand-written or truncated transcript can hold anything.
    """
    message = record.get("message")
    return message.get("content") if isinstance(message, dict) else None


def _tool_names(content: Any) -> list[str]:
    if not isinstance(content, list):
        return []
    return [
        block["name"]
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "tool_use"
        and block.get("name")
    ]


def _first_record_type(path: Path) -> str | None:
    """The `type` field of a transcript's first parseable line, or None.

    Read failures and parse failures both return None rather than raise:
    the caller falls back to the Claude reader, which repeats the same
    open and hits the same `OSError`, so a missing file still yields the
    documented empty result through the one path that already handles it.
    """
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except ValueError:
                    return None
                return record.get("type") if isinstance(record, dict) else None
    except OSError:
        return None
    return None


def transcript_activity(transcript_path: str | Path | None) -> dict[str, Any]:
    """Return {"tool_sequence": [...], "turn_count": n} for a transcript.

    An unreadable, missing or malformed transcript yields an empty sequence
    and a zero count: the caller keeps whatever the event supplied. A
    `transcript_path` that is neither text nor a path is refused the same
    way, since it comes from the hook event's own JSON envelope and nothing
    there is typed.

    postcondition: a Codex rollout (first record's `type` ==
    `"session_meta"`) is read by `rollout_activity`; every other transcript,
    including one whose first line cannot be read or parsed, is read by the
    Claude reader below — byte-identical to this function's pre-Codex
    behaviour, since that reader already degrades the same inputs to the
    same empty result.
    """
    empty: dict[str, Any] = {"tool_sequence": [], "turn_count": 0}
    if not transcript_path or not isinstance(transcript_path, (str, PathLike)):
        return empty
    path = Path(transcript_path)
    if _first_record_type(path) == "session_meta":
        return rollout_activity(path, MAX_TOOL_SEQUENCE)
    return _claude_transcript_activity(path, empty)


def _claude_transcript_activity(path: Path, empty: dict[str, Any]) -> dict[str, Any]:
    """The original reader for Claude Code's `{"type": "assistant", ...}`
    transcript shape, unchanged since ADR-1072/ADR-1073 — see
    `transcript_activity`'s docstring for the dispatch that reaches it.

    A line that does not parse as JSON, or parses as anything other than an
    object, is skipped and the rest of the file is still read — this runs
    inside the SessionEnd hook, where an exception would cost the session
    its log entry and its profile update.
    """
    sequence: list[str] = []
    turns = 0
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                if '"assistant"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict) or record.get("type") != "assistant":
                    continue
                turns += 1
                if len(sequence) < MAX_TOOL_SEQUENCE:
                    sequence.extend(_tool_names(_message_content(record)))
    except OSError:
        return empty
    return {"tool_sequence": sequence[:MAX_TOOL_SEQUENCE], "turn_count": turns}
