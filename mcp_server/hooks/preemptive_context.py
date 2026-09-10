#!/usr/bin/env python3
"""Claude Code PostToolUse hook — preemptive memory priming.

When an agent reads or edits a file, this hook "primes" related memories
by boosting their heat. This makes them surface naturally in subsequent
recall() calls without explicit querying — implementing the "proactive
brain" pattern where context pre-activates related representations.

Strategy:
  On Edit/Write/Read of a file, boost heat of memories mentioning that
  file. This is "spreading activation" — the file access cue propagates
  activation to related memory nodes via heat boost. Those memories then
  rank higher in the next recall() call.

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

source: ADR-0496"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from mcp_server.shared.hook_state_paths import cooldown_path

_LOG_PREFIX = "[cortex-preemptive]"
_DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/cortex")
_HEAT_BOOST = 0.1  # Small boost — primes without dominating
_COOLDOWN_SECONDS = 60
_COOLDOWN_FILE = cooldown_path("cortex_preemptive_cooldown.json")

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
    except (OSError, ValueError, TypeError):
        # Cooldown cache is disposable: unreadable/corrupt state means
        # "no cooldown", and the next _update_cooldown rewrites the file.
        pass
    return False


# source: ADR-0496
_MAX_COOLDOWN_ENTRIES = 50


def _update_cooldown(file_path: str) -> None:
    """Record that we scanned this file, including a miss."""
    try:
        data = {}
        if _COOLDOWN_FILE.exists():
            data = json.loads(_COOLDOWN_FILE.read_text())
        data[file_path] = time.time()
        # Prune old entries
        if len(data) > _MAX_COOLDOWN_ENTRIES:
            sorted_items = sorted(data.items(), key=lambda x: x[1], reverse=True)
            data = dict(sorted_items[:_MAX_COOLDOWN_ENTRIES])
        _COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _COOLDOWN_FILE.write_text(json.dumps(data))
    except (OSError, ValueError, TypeError):
        # Cooldown cache is disposable: a failed write only means the next
        # run skips the cooldown, which is safe.
        pass


def _prime_file_memories(file_path: str) -> int:
    """Boost heat of memories related to this file.

    Implements Collins & Loftus 1975 spreading activation: file access
    cue propagates activation (heat) to related memory nodes.

    Returns number of memories primed.
    """
    try:
        import psycopg  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
    except ImportError:
        return 0

    try:
        conn = psycopg.connect(_DATABASE_URL, autocommit=True)
    except psycopg.Error:
        return 0

    filename = Path(file_path).name
    # source: ADR-0496
    try:
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
        count = result.rowcount if result else 0
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
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
    _update_cooldown(file_path)
    if count > 0:
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
    # No-op inside the headless wiki-authoring subprocess (see
    # _headless_guard): prevents recursion + memory pollution when
    # ``claude -p --setting-sources user`` loads the user hooks.
    from mcp_server.hooks._headless_guard import (
        exit_if_headless_authoring_child,
    )

    exit_if_headless_authoring_child()
    main()
