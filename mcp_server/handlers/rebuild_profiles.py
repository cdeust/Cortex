"""Handler for the rebuild_profiles tool — full profile rescan."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from mcp_server.core.profile_assembler import build_domain_profiles
from mcp_server.infrastructure.brain_index_store import load_brain_index
from mcp_server.infrastructure.profile_store import load_profiles, save_profiles
from mcp_server.infrastructure.scanner import (
    discover_all_memories,
    discover_conversations,
    group_by_project,
)
from mcp_server.handlers._tool_meta import IDEMPOTENT_WRITE

schema = {
    "title": "Rebuild profiles",
    "annotations": IDEMPOTENT_WRITE,
    "description": (
        "Full rescan of Claude Code session data to rebuild methodology "
        "profiles from scratch. Walks ~/.claude/projects/, parses JSONL "
        "transcripts, groups by project, and re-derives per-domain "
        "cognitive style (Felder-Silverman), entry patterns, blind spots, "
        "and cross-domain bridges via the profile_assembler pipeline. Use "
        "this on first install, after a major workflow change, or when "
        "`query_methodology` returns coldStart=true. Skipped automatically "
        "if profiles are <1h old unless force=true. Distinct from "
        "`query_methodology` (read the cached profile, no rescan), "
        "`record_session_end` (incremental EMA update for one session, no "
        "full rebuild), and `detect_domain` (just classifies, doesn't "
        "rebuild). Mutates ~/.claude/methodology/profiles.json. Latency "
        "<10s on typical histories. Returns {rebuilt_domains, "
        "total_sessions, duration_ms}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "Rebuild only this single domain instead of the full set. "
                    "Useful for fast targeted refresh after heavy work in one area."
                ),
                "examples": ["cortex", "ai-architect"],
            },
            "force": {
                "type": "boolean",
                "description": (
                    "Bypass the 1-hour freshness check and rebuild even if "
                    "profiles were updated recently."
                ),
                "default": False,
            },
        },
    },
}


def _check_skip(force: bool) -> dict | None:
    """Return a skip response if profiles are recent and force is False."""
    if force:
        return None
    profiles = load_profiles()
    updated_at = profiles.get("updatedAt")
    if not updated_at:
        return None
    try:
        age_ms = (
            datetime.now(timezone.utc)
            - datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        ).total_seconds() * 1000
        if age_ms < 3600000 and len(profiles.get("domains", {})) > 0:
            return {
                "skipped": True,
                "reason": "Profiles updated less than 1 hour ago. Use force=true to override.",
                "domains": list(profiles.get("domains", {}).keys()),
                "updatedAt": updated_at,
            }
    except Exception:
        pass
    return None


async def handler(args: dict | None = None) -> dict:
    args = args or {}
    domain = args.get("domain")

    skip = _check_skip(args.get("force", False))
    if skip:
        return skip

    start_time = time.monotonic()
    memories = discover_all_memories()
    conversations = discover_conversations()
    by_project = group_by_project(conversations)

    updated_profiles = build_domain_profiles(
        existing_profiles=load_profiles(),
        conversations=conversations,
        memories=memories,
        brain_index=load_brain_index(),
        by_project=by_project,
        target_domain=domain,
    )
    save_profiles(updated_profiles)

    duration = int((time.monotonic() - start_time) * 1000)
    return {
        "domains": list(updated_profiles.get("domains", {}).keys()),
        "totalSessions": len(conversations),
        "totalMemories": len(memories),
        "duration": duration,
    }
