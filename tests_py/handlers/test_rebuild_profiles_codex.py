"""rebuild_profiles creates a domain from a Codex-only history (issue #726).

Before #726 the rebuild walked ``~/.claude/projects`` only; a user who works
in Codex alone got no domain, whatever their history held.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from mcp_server.handlers.rebuild_profiles import handler

_CWD = "/work/codex-only-repo"


def _rollout(root: Path, name: str, prompt: str) -> None:
    records = [
        {
            "timestamp": "2026-09-01T00:00:00Z",
            "type": "session_meta",
            "payload": {"id": name, "cwd": _CWD, "thread_source": "user"},
        },
        {
            "timestamp": "2026-09-01T00:00:01Z",
            "type": "event_msg",
            "payload": {"type": "user_message", "message": prompt},
        },
        {
            "timestamp": "2026-09-01T00:00:02Z",
            "type": "response_item",
            "payload": {"type": "function_call", "name": "exec", "arguments": "{}"},
        },
        {
            "timestamp": "2026-09-01T00:05:00Z",
            "type": "response_item",
            "payload": {"type": "message", "role": "assistant", "content": []},
        },
    ]
    path = root / "codex" / "sessions" / "2026" / "09" / "01" / f"rollout-{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def _outcomes(result: dict) -> list[dict]:
    return result["domainOutcomes"]


def test_codex_only_history_creates_its_domain(hermetic_claude_dirs):
    _rollout(hermetic_claude_dirs, "a", "fix the failing parser test")
    _rollout(hermetic_claude_dirs, "b", "refactor the parser module")

    result = asyncio.run(handler({"force": True}))

    assert result["totalSessions"] == 2
    assert len(result["domains"]) == 1
    [outcome] = _outcomes(result)
    assert outcome["action"] == "created"
    assert outcome["scannedSessions"] == 2
    assert outcome["resultingSessions"] == 2


def test_rescan_does_not_duplicate_codex_sessions(hermetic_claude_dirs):
    _rollout(hermetic_claude_dirs, "a", "fix the failing parser test")
    _rollout(hermetic_claude_dirs, "b", "refactor the parser module")
    asyncio.run(handler({"force": True}))

    again = asyncio.run(handler({"force": True}))

    [outcome] = _outcomes(again)
    assert outcome["storedSessions"] == 2
    assert outcome["scannedSessions"] == 2
    assert outcome["resultingSessions"] == 2
