#!/usr/bin/env python3
"""Claude Code PostToolUse hook — preemptive memory priming.

When an agent reads or edits a file, this hook "primes" related memories
by boosting their heat. This makes them surface naturally in subsequent
recall() calls without explicit querying — implementing the "proactive
brain" pattern where context pre-activates related representations.

Paper backing:
  - Bar 2007 "The proactive brain" (Trends in Cognitive Sciences):
    the brain continuously generates top-down predictions from context,
    pre-activating representations before bottom-up input arrives.
  - Collins & Loftus 1975: spreading activation — file path as cue node
    activates related memory nodes in the knowledge graph.
  - Smith & Vela 2001: context reinstatement at retrieval produces a
    reliable memory benefit (d=0.28, ~15-20% boost).

Source backing:
  - Claude Code hooks system (lesson 10): PreToolUse exit 0 does NOT
    inject context (stdout not shown to model). PostToolUse is the
    correct hook for capturing context and influencing subsequent behavior.
  - Claude Code auto-memory (lesson 40): "findRelevantMemories" surfaces
    relevant files before the main agent responds — analogous to our
    heat priming making memories surface in recall.

Strategy:
  On Edit/Write/Read of a file, boost heat of memories mentioning that
  file. This is "spreading activation" — the file access cue propagates
  activation to related memory nodes via heat boost. Those memories then
  rank higher in the next recall() call.

  This avoids the PreToolUse injection limitation: instead of trying to
  push context into the model (which PreToolUse can't do), we pull it
  by making relevant memories hotter so they surface organically.

Installation
------------
Add to ``~/.claude/settings.json`` under hooks::

    {
        "hooks": {
            "PostToolUse": [{
                "type": "command",
                "command": "python3 -m mcp_server.hooks.preemptive_context",
                "timeout": 3
            }]
        }
    }

Invariants
----------
- Fires on Edit/Write/Read tools only
- Non-blocking: exits quickly, errors logged to stderr
- Heat boost is small (0.1) — primes but doesn't dominate ranking
- Cooldown per file (60s) — avoids repeated boosting on rapid edits
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
_HEAT_BOOST = 0.1  # Small boost — primes without dominating
_COOLDOWN_SECONDS = 60
_COOLDOWN_FILE = Path("/tmp/cortex_preemptive_cooldown.json")

# Tools that indicate file interaction worth priming for
_FILE_TOOLS = {"Edit", "Write", "Read"}


def _log(msg: str) -> None:
    print(f"{_LOG_PREFIX} {msg}", file=sys.stderr)


def _check_cooldown(file_path: str) -> bool:
    """Return True if this file was primed recently (skip)."""
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
    """Record that we primed memories for this file."""
    try:
        data = {}
        if _COOLDOWN_FILE.exists():
            data = json.loads(_COOLDOWN_FILE.read_text())
        data[file_path] = time.time()
        # Prune old entries
        if len(data) > 50:
            sorted_items = sorted(data.items(), key=lambda x: x[1], reverse=True)
            data = dict(sorted_items[:50])
        _COOLDOWN_FILE.write_text(json.dumps(data))
    except Exception:
        pass


def _prime_file_memories(file_path: str) -> int:
    """Boost heat of memories related to this file.

    Implements Collins & Loftus 1975 spreading activation: file access
    cue propagates activation (heat) to related memory nodes.

    Returns number of memories primed.
    """
    try:
        import psycopg
    except ImportError:
        return 0

    try:
        conn = psycopg.connect(_DATABASE_URL, autocommit=True)
    except Exception:
        return 0

    filename = Path(file_path).name
    # A3 writer refactor (Phase 3 step 5):
    # Post-A3 (flag=true, schema migrated): boost heat_base and refresh
    # heat_base_set_at. effective_heat() then reads the boost via the
    # post-migration read path. Pre-A3: legacy heat column path.
    # Source: phase-3-a3-migration-design.md §3.4.
    from mcp_server.infrastructure.memory_config import get_memory_settings

    settings = get_memory_settings()
    a3_lazy = getattr(settings, "A3_LAZY_HEAT", False)
    try:
        if a3_lazy:
            result = conn.execute(
                """
                UPDATE memories
                SET heat_base = LEAST(heat_base + %s, 1.0),
                    heat_base_set_at = NOW(),
                    last_accessed = NOW()
                WHERE NOT is_benchmark
                  AND heat_base < 1.0
                  AND (content ILIKE %s OR content ILIKE %s)
                """,
                (_HEAT_BOOST, f"%{file_path}%", f"%{filename}%"),
            )
        else:
            result = conn.execute(
                """
                UPDATE memories
                SET heat = LEAST(heat + %s, 1.0),
                    last_accessed = NOW()
                WHERE NOT is_benchmark
                  AND heat < 1.0
                  AND (content ILIKE %s OR content ILIKE %s)
                """,
                (_HEAT_BOOST, f"%{file_path}%", f"%{filename}%"),
            )
        count = result.rowcount if result else 0
    except Exception as exc:
        _log(f"prime failed: {exc}")
        count = 0

    conn.close()
    return count


def process_event(event: dict[str, Any]) -> None:
    """Process PostToolUse event and prime related memories."""
    tool_name = event.get("tool_name", "")

    if tool_name not in _FILE_TOOLS:
        return

    tool_input = event.get("tool_input") or {}
    file_path = tool_input.get("file_path", "")

    if not file_path:
        return

    if _check_cooldown(file_path):
        return

    count = _prime_file_memories(file_path)
    if count > 0:
        _update_cooldown(file_path)
        _log(f"primed {count} memories for {Path(file_path).name}")


def main() -> None:
    """Entry point — read JSON event from stdin."""
    if sys.stdin.isatty():
        return

    raw = sys.stdin.read().strip()
    if not raw:
        return

    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        return

    process_event(event)


if __name__ == "__main__":
    main()
