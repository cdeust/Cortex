#!/usr/bin/env python3
"""Claude Code PreToolUse hook — preemptive context injection.

Injects relevant memory context before file edits, implementing the
"proactive brain" pattern: context triggers anticipatory retrieval
BEFORE the user/agent explicitly asks.

Paper backing:
  - Bar 2007 "The proactive brain: using analogies and associations to
    generate predictions" (Trends in Cognitive Sciences): the brain
    continuously generates top-down predictions from context, pre-activating
    representations before bottom-up input arrives.
  - Collins & Loftus 1975: spreading activation — file path as cue node
    activates related memories in the knowledge graph.
  - Smith & Vela 2001: context reinstatement at retrieval (~15-20% boost
    when encoding context matches retrieval context, d=0.28).
  - Godden & Baddeley 1975: ~30% recall advantage with context match.
  - McDaniel & Einstein 2007: spontaneous retrieval is cue-driven and
    automatic — no active monitoring needed.

Source backing:
  - Claude Code hooks system (markdown.engineering/learn-claude-code/10-hooks-system):
    PreToolUse hooks fire before tool execution, can inject context via
    exit code 0 (stdout shown to model).
  - Claude Code auto-memory (lesson 40): memories extract post-sampling,
    surface pre-query via relevance selector.

Strategy:
  Only fires on Edit/Write tools (file modifications). Extracts the
  file_path from tool input, queries memory for past context about that
  file (decisions, bugs, patterns). Injects as a brief context note
  visible to the model.

  Gated by:
    - Tool type (Edit/Write only — read-only tools don't need context)
    - Heat threshold (only high-heat memories — avoid noise)
    - Result limit (max 2 memories — keep injection compact)
    - Cooldown (same file within 60s → skip, avoid repetition)

Installation
------------
Add to ``~/.claude/settings.json`` under hooks::

    {
        "hooks": {
            "PreToolUse": [{
                "type": "command",
                "command": "python3 -m mcp_server.hooks.preemptive_context",
                "timeout": 5,
                "matcher": "Edit"
            }],
            "PreToolUse": [{
                "type": "command",
                "command": "python3 -m mcp_server.hooks.preemptive_context",
                "timeout": 5,
                "matcher": "Write"
            }]
        }
    }

Invariants
----------
- Exit 0: stdout shown to model as context (preemptive injection)
- Exit 1: skip (no relevant context found)
- Non-blocking: must complete within 5s timeout
- Logs to stderr only
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_LOG_PREFIX = "[cortex-preemptive]"
_DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/cortex")
_MIN_HEAT = 0.3  # Only inject high-heat memories
_MAX_RESULTS = 2  # Keep injection compact
_COOLDOWN_SECONDS = 60  # Don't repeat for same file within 60s

# Simple in-memory cooldown tracker (resets each hook invocation)
_COOLDOWN_FILE = Path("/tmp/cortex_preemptive_cooldown.json")


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", file=sys.stderr)


def _check_cooldown(file_path: str) -> bool:
    """Return True if this file was injected recently (skip)."""
    try:
        if _COOLDOWN_FILE.exists():
            data = json.loads(_COOLDOWN_FILE.read_text())
            last_time = data.get(file_path, 0)
            if time.time() - last_time < _COOLDOWN_SECONDS:
                return True
    except Exception:
        pass
    return False


def _update_cooldown(file_path: str) -> None:
    """Record that we injected context for this file."""
    try:
        data = {}
        if _COOLDOWN_FILE.exists():
            data = json.loads(_COOLDOWN_FILE.read_text())
        data[file_path] = time.time()
        # Prune old entries (keep last 50)
        if len(data) > 50:
            sorted_items = sorted(data.items(), key=lambda x: x[1], reverse=True)
            data = dict(sorted_items[:50])
        _COOLDOWN_FILE.write_text(json.dumps(data))
    except Exception:
        pass


def _fetch_file_context(file_path: str) -> list[dict]:
    """Query PG for memories related to this file path.

    Uses direct SQL for speed (no embedding model load needed).
    Matches via:
      1. Content containing the file path (exact)
      2. Content containing the filename (fuzzy)
    Filtered by heat >= threshold.
    """
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        return []

    try:
        conn = psycopg.connect(_DATABASE_URL, row_factory=dict_row, autocommit=True)
    except Exception:
        return []

    filename = Path(file_path).name
    try:
        rows = conn.execute(
            """
            SELECT id, content, heat, tags, agent_context
            FROM memories
            WHERE heat >= %s
              AND NOT is_benchmark
              AND (content ILIKE %s OR content ILIKE %s)
            ORDER BY heat DESC
            LIMIT %s
            """,
            (
                _MIN_HEAT,
                f"%{file_path}%",
                f"%{filename}%",
                _MAX_RESULTS + 2,  # Fetch extra for filtering
            ),
        ).fetchall()
    except Exception:
        conn.close()
        return []

    conn.close()

    results = []
    for r in rows:
        content = r.get("content", "")
        # Skip very long memories (just tool output dumps)
        if len(content) > 2000:
            continue
        results.append(
            {
                "content": content[:300],
                "heat": r.get("heat", 0),
                "agent": r.get("agent_context", ""),
            }
        )

    return results[:_MAX_RESULTS]


def process_event(event: dict[str, Any]) -> None:
    """Process PreToolUse event and inject context if relevant."""
    tool_name = event.get("tool_name", "")

    if tool_name not in ("Edit", "Write"):
        sys.exit(1)  # Skip — not a file modification tool

    tool_input = event.get("tool_input") or {}
    file_path = tool_input.get("file_path", "")

    if not file_path:
        sys.exit(1)

    # Cooldown check
    if _check_cooldown(file_path):
        _log(f"cooldown: {file_path}")
        sys.exit(1)

    # Fetch context
    memories = _fetch_file_context(file_path)

    if not memories:
        sys.exit(1)  # No relevant context

    # Build injection
    lines = [f"Cortex: past context for `{Path(file_path).name}`:"]
    for m in memories:
        agent_prefix = f"[{m['agent']}] " if m.get("agent") else ""
        # Truncate to first meaningful line
        first_line = m["content"].split("\n")[0][:150]
        lines.append(f"  - {agent_prefix}{first_line}")

    # Output to stdout (shown to model via exit 0)
    print("\n".join(lines))
    _update_cooldown(file_path)
    _log(f"injected {len(memories)} memories for {Path(file_path).name}")
    sys.exit(0)


def main() -> None:
    """Entry point — read JSON event from stdin."""
    if sys.stdin.isatty():
        sys.exit(1)

    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(1)

    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(1)

    process_event(event)


if __name__ == "__main__":
    main()
