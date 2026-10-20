"""SessionStart hook configuration, stderr logging and event reading.

source: ADR-0498"""

from __future__ import annotations

import json
import os
import sys

from mcp_server.hooks.stdin_event import read_event_text


# source: ADR-1110 — no default URL; settle_backend sets it only for PostgreSQL
_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_HOT_LIMIT = int(os.environ.get("CORTEX_SESSION_START_LIMIT", "8"))
_MIN_HEAT = float(os.environ.get("CORTEX_SESSION_START_MIN_HEAT", "0.4"))
_ANCHOR_LIMIT = int(os.environ.get("CORTEX_SESSION_START_ANCHOR_LIMIT", "5"))
_PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", "")


def _log(msg: str) -> None:
    print(f"[session-start-hook] {msg}", file=sys.stderr)


def _read_event() -> dict:
    """Read the SessionStart hook event from stdin, tolerantly.

    Claude Code pipes the event JSON ({"session_id", "transcript_path",
    "cwd", ...}) to every hook. A manual/tty run, an empty pipe, or
    malformed JSON all degrade to {} — the banner never depends on the
    event; only the receipt's session identity does (correction 7).
    """
    if sys.stdin.isatty():
        return {}
    try:
        raw = read_event_text(_log).strip()
        return json.loads(raw) if raw else {}
    except (OSError, ValueError):
        return {}
