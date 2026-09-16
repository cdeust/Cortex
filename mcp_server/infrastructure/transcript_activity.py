"""What a session actually did, read from its transcript.

The SessionEnd payload carries `session_id`, `transcript_path` and `cwd`; it
carries neither the tools the session used nor its turn count, so
`hooks/session_lifecycle.py` wrote every session entry with `toolsUsed: []`
and `turnCount: 0` and procedural mining never had an input (issue #591).

The transcript has both. This reads it as a stream, keeping the tool calls in
the order they were made, repetitions included, because `core.procedural_memory`
mines contiguous subsequences: a deduplicated set would describe a sequence
nobody performed.

source: ADR-1072"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# A session's tool calls, capped so one long session cannot dominate the
# session log.
# source: measured 2026-09-16 over the 374 transcripts under
# ~/.claude/projects, where the largest carried 539 tool calls and the
# median non-empty one 34; the decision is recorded in ADR number 1072.
MAX_TOOL_SEQUENCE = 2000


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


def transcript_activity(transcript_path: str | Path | None) -> dict[str, Any]:
    """Return {"tool_sequence": [...], "turn_count": n} for a transcript.

    An unreadable, missing or malformed transcript yields an empty sequence
    and a zero count: the caller keeps whatever the event supplied. A line
    that does not parse as JSON, or parses as anything other than an object,
    is skipped and the rest of the file is still read — this runs inside the
    SessionEnd hook, where an exception would cost the session its log entry
    and its profile update.
    """
    empty: dict[str, Any] = {"tool_sequence": [], "turn_count": 0}
    if not transcript_path:
        return empty
    path = Path(transcript_path)
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
                    content = (record.get("message") or {}).get("content")
                    sequence.extend(_tool_names(content))
    except OSError:
        return empty
    return {"tool_sequence": sequence[:MAX_TOOL_SEQUENCE], "turn_count": turns}
