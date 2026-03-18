#!/usr/bin/env python3
"""Claude Code hook script for SessionEnd events.

Problem Statement
-----------------
Profile updates should happen automatically when sessions end, without
requiring manual invocation of ``record_session_end``.

Approach
--------
Standalone script that reads hook event data from stdin (JSON), determines
the relevant domain, logs the session, and updates profiles via the
profile-builder module.

Installation
------------
Add to ``~/.claude/settings.json`` under hooks::

    {
        "hooks": {
            "SessionEnd": [{
                "command": "python -m mcp_server.hooks.session_lifecycle"
            }]
        }
    }

Invariants
----------
- Reads event from stdin (single JSON line)
- Non-blocking: exits quickly even if profile update fails
- Logs to stderr only
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

from mcp_server.infrastructure.profile_store import load_profiles, save_profiles
from mcp_server.infrastructure.session_store import load_session_log, save_session_log
from mcp_server.core.profile_builder import apply_session_update
from mcp_server.shared.project_ids import (
    cwd_to_project_id,
    project_id_to_label,
    domain_id_from_label,
)
from mcp_server.shared.categorizer import categorize

_LOG_PREFIX = "[methodology-hook]"

# Maximum number of sessions to retain in the session log.
MAX_SESSION_LOG_ENTRIES = 1000


def _log(msg: str) -> None:
    """Write a diagnostic message to stderr."""
    print(f"{_LOG_PREFIX} {msg}", file=sys.stderr)


def _resolve_domain(event: dict[str, Any], profiles: dict) -> str:
    """Determine domain ID from event data and existing profiles.

    Resolution order:
    1. Match *event.project* (or derived project ID from *event.cwd*) against
       known domain project lists.
    2. Fall back to label-based domain derivation.
    3. Default to ``"unknown"``.
    """
    proj_id = event.get("project") or cwd_to_project_id(event.get("cwd"))

    if proj_id:
        # Try matching against existing domain project lists
        for domain_id, domain in (profiles.get("domains") or {}).items():
            if proj_id in (domain.get("projects") or []):
                return domain_id

        # Derive from label
        label = project_id_to_label(proj_id)
        derived = domain_id_from_label(label)
        if derived:
            return derived

    return "unknown"


def _run_consolidation() -> None:
    """Run memory consolidation (decay + compression) at session end.

    Non-blocking: logs errors but never raises.
    """
    try:
        import asyncio
        from mcp_server.handlers.consolidate import handler as consolidate_handler

        result = asyncio.run(consolidate_handler({"decay": True, "compress": True}))
        decayed = result.get("decay", {}).get("memories_decayed", 0)
        compressed = result.get("compression", {}).get(
            "compressed_to_gist", 0
        ) + result.get("compression", {}).get("compressed_to_tag", 0)
        _log(f"Consolidation: {decayed} decayed, {compressed} compressed")
    except Exception as exc:
        _log(f"Consolidation failed (non-fatal): {exc}")


def _build_session_entry(event: dict[str, Any], domain_id: str) -> dict[str, Any]:
    """Build a session log entry from event data."""
    keywords = event.get("keywords") or []
    return {
        "sessionId": event["session_id"],
        "domain": domain_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project": event.get("project") or cwd_to_project_id(event.get("cwd")),
        "cwd": event.get("cwd"),
        "duration": event.get("duration"),
        "turnCount": event.get("turn_count", 0),
        "toolsUsed": event.get("tools_used") or [],
        "category": categorize(" ".join(keywords)) if keywords else "general",
        "entryKeywords": keywords,
    }


def _append_session(session_log: dict, entry: dict[str, Any]) -> None:
    """Append a session entry to the log, capping at MAX_SESSION_LOG_ENTRIES."""
    sessions = session_log.get("sessions") or []
    sessions.append(entry)
    if len(sessions) > MAX_SESSION_LOG_ENTRIES:
        sessions = sessions[-MAX_SESSION_LOG_ENTRIES:]
    session_log["sessions"] = sessions


def process_event(event: dict[str, Any] | None) -> None:
    """Process a single session lifecycle event.

    Parameters
    ----------
    event:
        Hook event data. Must contain at least ``session_id``.
        Optional fields: ``cwd``, ``project``, ``tools_used``, ``duration``,
        ``turn_count``, ``keywords``.
    """
    if not event or not event.get("session_id"):
        _log("No session_id in event, skipping")
        return

    profiles = load_profiles()
    log = load_session_log()

    domain_id = _resolve_domain(event, profiles)
    _append_session(log, _build_session_entry(event, domain_id))
    save_session_log(log)

    dp = (profiles.get("domains") or {}).get(domain_id)
    if dp:
        apply_session_update(
            domain_profile=dp,
            session_data={
                "duration": event.get("duration"),
                "tools_used": event.get("tools_used"),
                "turn_count": event.get("turn_count"),
            },
        )
        save_profiles(profiles)
        _log(f'Updated profile for domain "{domain_id}"')
    else:
        _log(f'No profile for domain "{domain_id}", logged session only')

    _run_consolidation()


def main() -> None:
    """Entry point — read JSON event from stdin and process it."""
    if sys.stdin.isatty():
        _log("No stdin data (TTY mode), exiting")
        return

    raw = sys.stdin.read().strip()
    if not raw:
        _log("Empty stdin, exiting")
        return

    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        _log(f"Failed to parse event: {exc}")
        return

    process_event(event)


if __name__ == "__main__":
    main()
