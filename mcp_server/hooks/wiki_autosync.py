#!/usr/bin/env python3
"""Hook: opt-in wiki autosync after SessionEnd.

Renders the read-only Markdown wiki projection of Cortex memory state.
Disabled by default; enable with::

    export CORTEX_WIKI_AUTOSYNC=1

The hook is intentionally minimal — it never blocks the session end path
and never raises. All errors go to stderr. PostgreSQL remains the single
source of truth; this only refreshes a derived view.

Wire-up (optional, in plugin.json or ~/.claude/settings.json)::

    {
      "hooks": {
        "SessionEnd": [{
          "hooks": [{
            "type": "command",
            "command": "python -m mcp_server.hooks.wiki_autosync",
            "timeout": 10
          }]
        }]
      }
    }
"""

from __future__ import annotations

import asyncio
import os
import sys


def _enabled() -> bool:
    return os.environ.get("CORTEX_WIKI_AUTOSYNC", "").strip() not in ("", "0", "false")


def main() -> int:
    if not _enabled():
        return 0
    try:
        from mcp_server.handlers.wiki_sync import handler

        result = asyncio.run(handler({}))
    except Exception as exc:  # noqa: BLE001 — hook must never raise
        print(f"[wiki_autosync] skipped: {exc}", file=sys.stderr)
        return 0
    print(
        f"[wiki_autosync] wrote={result.get('written')} "
        f"skipped={result.get('skipped')} pruned={result.get('pruned')} "
        f"root={result.get('root')}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
