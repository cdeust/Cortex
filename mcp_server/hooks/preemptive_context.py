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
- Fires on file tools and completed explicit shell file reads
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
from mcp_server.shared.project_scope import resolve_project_root
from mcp_server.hooks.shell_read_events import completed_shell_read
from mcp_server.infrastructure.file_memory_priming import prime_file_memories
from mcp_server.infrastructure.memory_store import get_shared_store

_LOG_PREFIX = "[cortex-preemptive]"
_HEAT_BOOST = 0.1  # source: ADR-0496 — preserved existing activation increment
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


def _prime_file_memories(
    file_path: str | list[str], project: str | None = None
) -> int | None:
    """One atomic boost for all cues in this tool call (source: ADR-1086)."""
    paths = [file_path] if isinstance(file_path, str) else file_path
    try:
        return prime_file_memories(get_shared_store(), paths, project, _HEAT_BOOST)
    except Exception as exc:  # noqa: BLE001 — hook boundary; storage errors are logged
        _log(f"prime failed: {exc}")
        return None


def _event_paths(
    event: dict[str, Any], project: str | None
) -> tuple[list[str], str | None]:
    tool = event.get("tool_name", "")
    if tool in {"Bash", "exec_command", "shell_command", "write_stdin"}:
        return completed_shell_read(
            event, project, _COOLDOWN_FILE.parent / "pending-reads"
        )
    inputs = event.get("tool_input") or {}
    path = inputs.get("file_path") if isinstance(inputs, dict) else None
    if tool not in _FILE_TOOLS or not isinstance(path, str) or not path:
        return [], project
    base = event.get("cwd") or project
    if not Path(path).is_absolute() and not base:
        return [], project
    return [str((Path(base or "/") / path).resolve())], project


def _cooldown_key(path: str, project: str | None) -> str:
    return json.dumps([project, path])


def process_event(event: dict[str, Any]) -> None:
    """Process completed file-access cues; scope every activation."""
    if (
        not isinstance(event, dict)
        or event.get("hook_event_name", "PostToolUse") != "PostToolUse"
    ):
        return
    project = resolve_project_root(event, os.environ)
    if project:
        project = str(Path(project).resolve())
    try:
        paths, project = _event_paths(event, project)
    except (OSError, ValueError, TypeError) as exc:
        _log(f"read event rejected: {exc}")
        return
    paths = list(
        dict.fromkeys(
            p for p in paths if not _check_cooldown(_cooldown_key(p, project))
        )
    )
    if not paths:
        return
    count = _prime_file_memories(paths[0] if len(paths) == 1 else paths, project)
    if count is None:
        return
    for path in paths:
        _update_cooldown(_cooldown_key(path, project))
    if count > 0:
        _log(f"primed {count} memories for {', '.join(Path(p).name for p in paths)}")


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
    from mcp_server.hooks.wiring import wire_composition_root  # noqa: PLC0415 — source: issue #560

    wire_composition_root()
    main()
