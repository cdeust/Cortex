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
import asyncio

_LOG_PREFIX = "[methodology-compaction-hook]"


def _log(msg: str) -> None:
    """Write a diagnostic message to stderr."""
    print(f"{_LOG_PREFIX} {msg}", file=sys.stderr)


def process_event(event: dict[str, Any] | None) -> None:
    """Process a compaction notification event.

    Creates an auto-checkpoint capturing whatever state is available.
    """
    try:
        from mcp_server.handlers.checkpoint import handler as checkpoint_handler  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
        from mcp_server.handlers.injection_receipts import (  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
            session_id_from_transcript,
        )
        from mcp_server.infrastructure.memory_config import get_memory_settings  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
        from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

        # Increment epoch BEFORE saving checkpoint so the new epoch is recorded
        settings = get_memory_settings()
        store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
        new_epoch = store.increment_epoch()
        _log(f"Epoch incremented to {new_epoch}")

        # Q2 alignment (decision 4255039 correction 7): Notification events
        # carry the same {"session_id", "transcript_path", ...} envelope as
        # every other Claude Code hook (session_start.py:49). Prefer the
        # transcript-stem identity when available; the raw event session_id
        # (defaulting to "auto-compaction" for synthetic/test events with no
        # transcript_path) is the documented degradation, not a regression.
        ev = event or {}
        result = asyncio.run(
            checkpoint_handler(
                {
                    "action": "save",
                    "session_id": session_id_from_transcript(ev.get("transcript_path"))
                    or ev.get("session_id", "auto-compaction"),
                    "current_task": "Auto-checkpoint before context compaction",
                    "custom_context": json.dumps(event) if event else "",
                }
            )
        )
        cp_id = result.get("checkpoint_id")
        _log(f"Auto-checkpoint saved: id={cp_id}, epoch={new_epoch}")

        # Run cascade advancement on compaction — consolidation during rest
        # (Dewar et al. 2012: rest after encoding boosts retention)
        try:
            from mcp_server.handlers.consolidation.cascade import (  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
                run_cascade_advancement,
            )

            cascade_result = run_cascade_advancement(store)
            advanced = cascade_result.get("advanced", 0)
            if advanced > 0:
                _log(f"Cascade: {advanced} memories advanced during compaction")
        except Exception as cascade_exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
            _log(f"Cascade failed (non-fatal): {cascade_exc}")
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
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
    # No-op inside the headless wiki-authoring subprocess (see
    # _headless_guard): prevents recursion + memory pollution when
    # ``claude -p --setting-sources user`` loads the user hooks.
    from mcp_server.hooks._headless_guard import (
        exit_if_headless_authoring_child,
    )

    exit_if_headless_authoring_child()
    main()
