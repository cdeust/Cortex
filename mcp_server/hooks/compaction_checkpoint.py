#!/usr/bin/env python3
"""Claude Code hook script for context compaction events.

Automatically saves a hippocampal checkpoint before context compaction
so working state can be restored after compaction via the `checkpoint`
MCP tool with action="restore".

Installation
------------
Add to ``~/.claude/settings.json`` under hooks::

    {
        "hooks": {
            "Notification": [{
                "matcher": "compacted",
                "hooks": [{
                    "type": "command",
                    "command": "python3 -m mcp_server.hooks.compaction_checkpoint",
                    "timeout": 5
                }]
            }]
        }
    }

Invariants
----------
- Reads event from stdin (single JSON line)
- Non-blocking: exits quickly even if checkpoint fails
- Logs to stderr only
"""

from __future__ import annotations

import json
import sys
from typing import Any

_LOG_PREFIX = "[methodology-compaction-hook]"


def _log(msg: str) -> None:
    """Write a diagnostic message to stderr."""
    print(f"{_LOG_PREFIX} {msg}", file=sys.stderr)


def process_event(event: dict[str, Any] | None) -> None:
    """Process a compaction notification event.

    Creates an auto-checkpoint capturing whatever state is available.
    """
    try:
        import asyncio

        from mcp_server.handlers.checkpoint import handler as checkpoint_handler
        from mcp_server.infrastructure.memory_config import get_memory_settings
        from mcp_server.infrastructure.memory_store import MemoryStore

        # Increment epoch BEFORE saving checkpoint so the new epoch is recorded
        settings = get_memory_settings()
        store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
        new_epoch = store.increment_epoch()
        _log(f"Epoch incremented to {new_epoch}")

        result = asyncio.run(
            checkpoint_handler(
                {
                    "action": "save",
                    "session_id": (event or {}).get("session_id", "auto-compaction"),
                    "current_task": "Auto-checkpoint before context compaction",
                    "custom_context": json.dumps(event) if event else "",
                }
            )
        )
        cp_id = result.get("checkpoint_id")
        _log(f"Auto-checkpoint saved: id={cp_id}, epoch={new_epoch}")
    except Exception as exc:
        _log(f"Auto-checkpoint failed (non-fatal): {exc}")


def main() -> None:
    """Entry point — read JSON event from stdin and process it."""
    if sys.stdin.isatty():
        _log("No stdin data (TTY mode), exiting")
        return

    raw = sys.stdin.read().strip()
    event = None
    if raw:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            _log(f"Failed to parse event: {exc}")

    process_event(event)


if __name__ == "__main__":
    main()
