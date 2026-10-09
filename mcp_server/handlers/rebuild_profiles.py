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
from mcp_server.observability import silent_failure

schema = {
    "title": "Rebuild profiles",
    "annotations": IDEMPOTENT_WRITE,
    "description": (
        "Full rescan of Claude Code session data to rebuild methodology "
        "profiles. Walks ~/.claude/projects/, parses JSONL transcripts, "
        "groups by project, and re-derives per-domain cognitive style "
        "(Felder-Silverman), entry patterns, blind spots, and cross-domain "
        "bridges via the profile_assembler pipeline. Use this on first "
        "install, after a major workflow change, or when `query_methodology` "
        "returns coldStart=true. Skipped automatically if profiles are <1h "
        "old unless force=true, which only bypasses that freshness check and "
        "never replaces a profile. Transcripts on disk are a sliding window "
        "(Claude Code deletes old ones) while a stored profile accumulates "
        "one session per `record_session_end`, so a domain whose scan sees "
        "fewer sessions than its stored profile records is KEPT unchanged "
        "and reported; only replace_accumulated_profiles=true replaces it "
        "with the smaller scan. Distinct from "
        "`query_methodology` (read the cached profile, no rescan), "
        "`record_session_end` (incremental EMA update for one session, no "
        "full rebuild), and `detect_domain` (just classifies, doesn't "
        "rebuild). Mutates ~/.claude/methodology/profiles.json. Latency "
        "<10s on typical histories. Returns {domains, totalSessions, "
        "totalMemories, duration, domainOutcomes: [{domain, action "
        "(created|rebuilt|kept|replaced), storedSessions, scannedSessions, "
        "resultingSessions}]}."
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
            "replace_accumulated_profiles": {
                "type": "boolean",
                "description": (
                    "DESTRUCTIVE. Replace a domain's stored profile with one "
                    "built only from the transcripts currently on disk even "
                    "when the scan sees fewer sessions than the profile "
                    "records (the accumulated session count and cognitive-"
                    "style state are lost; no transcript can rebuild them). "
                    "Independent of `force`, which only bypasses the 1-hour "
                    "freshness check. Every replaced domain is listed in "
                    "domainOutcomes with its before and after counts."
                ),
                "default": False,
            },
        },
    },
}


# source: ADR-0429
_PROFILE_FRESH_MS = 3600000


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
        if age_ms < _PROFILE_FRESH_MS and len(profiles.get("domains", {})) > 0:
            return {
                "skipped": True,
                "reason": (
                    "Profiles updated less than 1 hour ago. Use force=true to override."
                ),
                "domains": list(profiles.get("domains", {}).keys()),
                "updatedAt": updated_at,
            }
    except Exception as exc:  # noqa: BLE001 — freshness check failure degrades to a rebuild
        silent_failure.note("rebuild_profiles.freshness_check", exc)
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

    build = build_domain_profiles(
        existing_profiles=load_profiles(),
        conversations=conversations,
        memories=memories,
        brain_index=load_brain_index(),
        by_project=by_project,
        target_domain=domain,
        replace_accumulated=args.get("replace_accumulated_profiles", False),
    )
    updated_profiles = build.profiles
    save_profiles(updated_profiles)

    duration = int((time.monotonic() - start_time) * 1000)
    return {
        "domains": list(updated_profiles.get("domains", {}).keys()),
        "totalSessions": len(conversations),
        "totalMemories": len(memories),
        "domainOutcomes": [o.to_dict() for o in build.outcomes],
        "duration": duration,
    }
