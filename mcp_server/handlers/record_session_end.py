"""Handler for the record_session_end tool — incremental profile update.

Also stores an episodic memory summarizing the session and creates
prospective triggers from any TODO/decision keywords detected.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from mcp_server.core.profile_builder import apply_session_update
from mcp_server.core.session_critique import generate_critique
from mcp_server.infrastructure.profile_store import load_profiles, save_profiles
from mcp_server.infrastructure.session_store import load_session_log, save_session_log
from mcp_server.shared.categorizer import categorize
from mcp_server.shared.project_ids import (
    cwd_to_project_id,
    domain_id_from_label,
    project_id_to_label,
)

logger = logging.getLogger(__name__)

schema = {
    "description": "Incremental profile update after a session ends. <200ms.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "Session identifier"},
            "domain": {
                "type": "string",
                "description": "Domain ID (auto-detected if omitted)",
            },
            "tools_used": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tools used during the session",
            },
            "duration": {
                "type": "number",
                "description": "Session duration in milliseconds",
            },
            "turn_count": {
                "type": "number",
                "description": "Number of assistant turns",
            },
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key topics from the session",
            },
            "cwd": {"type": "string", "description": "Working directory"},
            "project": {"type": "string", "description": "Project identifier"},
        },
        "required": ["session_id"],
    },
}


# ── Memory integration (lazy) ───────────────────────────────────────────

_memory_available = None


def _build_session_summary(
    session_id: str,
    domain_id: str,
    category: str,
    keywords: list[str],
    tools_used: list[str],
    turn_count: int | None,
    duration: float | None,
) -> str:
    """Build a concise one-line summary of the session."""
    parts = [f"Session {session_id} in domain '{domain_id}'"]
    if category and category != "general":
        parts.append(f"category: {category}")
    if keywords:
        parts.append(f"topics: {', '.join(keywords[:10])}")
    if tools_used:
        parts.append(f"tools: {', '.join(tools_used[:10])}")
    if turn_count:
        parts.append(f"{turn_count} turns")
    if duration:
        mins = round(duration / 60000, 1)
        parts.append(f"{mins}min")
    return " | ".join(parts)


def _build_memory_tags(category: str, keywords: list[str]) -> list[str]:
    """Build deduplicated tags for a session memory."""
    return list(set(["session-summary", category] + (keywords or [])[:5]))


def _store_session_memory(
    session_id: str,
    domain_id: str,
    cwd: str,
    tools_used: list[str],
    keywords: list[str],
    duration: float | None,
    turn_count: int | None,
    category: str,
) -> dict[str, Any] | None:
    """Build remember-handler args for an episodic session memory."""
    global _memory_available
    if _memory_available is False:
        return None
    try:
        content = _build_session_summary(
            session_id,
            domain_id,
            category,
            keywords,
            tools_used,
            turn_count,
            duration,
        )
        _memory_available = True
        return {
            "content": content,
            "tags": _build_memory_tags(category, keywords),
            "directory": cwd or "",
            "domain": domain_id,
            "source": "session",
            "force": False,
        }
    except Exception as e:
        logger.debug("Memory system not available for session recording: %s", e)
        _memory_available = False
        return None


# ── Handler ──────────────────────────────────────────────────────────────


def _resolve_domain(
    domain: str | None,
    cwd: str | None,
    project: str | None,
    profiles: dict,
) -> str:
    """Resolve domain ID from explicit arg, cwd, or project."""
    if domain:
        return domain

    if not (cwd or project):
        return "unknown"

    proj_id = project or cwd_to_project_id(cwd)
    for d_id, d in (profiles.get("domains") or {}).items():
        if d.get("projects") and proj_id in d["projects"]:
            return d_id

    if proj_id:
        label = project_id_to_label(proj_id)
        return domain_id_from_label(label)

    return "unknown"


def _build_session_entry(
    session_id: str,
    domain_id: str,
    cwd: str | None,
    project: str | None,
    duration: float | None,
    turn_count: int | None,
    tools_used: list[str] | None,
    category: str,
    keywords: list[str] | None,
) -> dict[str, Any]:
    """Build the session log entry dict."""
    return {
        "sessionId": session_id,
        "domain": domain_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project": project or (cwd_to_project_id(cwd) if cwd else None),
        "cwd": cwd,
        "duration": duration,
        "turnCount": turn_count or 0,
        "toolsUsed": tools_used or [],
        "category": category,
        "entryKeywords": keywords or [],
    }


async def _try_store_memory(memory_args: dict[str, Any] | None) -> bool:
    """Attempt to store session memory via the remember handler."""
    if memory_args is None:
        return False
    try:
        from mcp_server.handlers.remember import handler as remember_handler

        mem_result = await remember_handler(memory_args)
        return mem_result.get("stored", False)
    except Exception as e:
        logger.debug("Failed to store session memory: %s", e)
        return False


def _try_generate_critique(
    tools_used: list[str],
    duration: float | None,
    turn_count: int | None,
) -> dict[str, Any] | None:
    """Generate session self-critique, returning None on failure."""
    try:
        critique_data = generate_critique(
            tools_used=tools_used,
            memories=[],
            duration_minutes=(duration / 60000) if duration else 0,
            turn_count=turn_count or 0,
        )
        return {
            "overall_score": critique_data["overall_score"],
            "top_suggestions": critique_data["top_suggestions"],
        }
    except Exception as e:
        logger.debug("Session critique generation failed (non-fatal): %s", e)
        return None


def _append_session_log(log: dict, entry: dict) -> None:
    """Append entry to session log with rolling 1000 cap."""
    log["sessions"].append(entry)
    if len(log["sessions"]) > 1000:
        log["sessions"] = log["sessions"][-1000:]
    save_session_log(log)


def _update_profile(
    profiles: dict,
    domain_id: str,
    duration: float | None,
    tools_used: list[str] | None,
    turn_count: int | None,
) -> tuple[bool, dict | None]:
    """Apply incremental profile update. Returns (updated, domain_profile)."""
    dp = (profiles.get("domains") or {}).get(domain_id)
    if not dp:
        return False, dp
    apply_session_update(
        domain_profile=dp,
        session_data={
            "duration": duration,
            "tools_used": tools_used,
            "turn_count": turn_count,
        },
    )
    save_profiles(profiles)
    return True, dp


async def handler(args: dict) -> dict:
    session_id = args["session_id"]
    cwd = args.get("cwd")
    project = args.get("project")
    tools_used = args.get("tools_used")
    duration = args.get("duration")
    turn_count = args.get("turn_count")
    keywords = args.get("keywords")

    profiles = load_profiles()
    domain_id = _resolve_domain(args.get("domain"), cwd, project, profiles)
    category = categorize(" ".join(keywords)) if keywords else "general"

    session_entry = _build_session_entry(
        session_id,
        domain_id,
        cwd,
        project,
        duration,
        turn_count,
        tools_used,
        category,
        keywords,
    )
    _append_session_log(load_session_log(), session_entry)

    profile_updated, dp = _update_profile(
        profiles,
        domain_id,
        duration,
        tools_used,
        turn_count,
    )

    memory_args = _store_session_memory(
        session_id=session_id,
        domain_id=domain_id,
        cwd=cwd or "",
        tools_used=tools_used or [],
        keywords=keywords or [],
        duration=duration,
        turn_count=turn_count,
        category=category,
    )

    return {
        "domain": domain_id,
        "profileUpdated": profile_updated,
        "memoryStored": await _try_store_memory(memory_args),
        "newPatterns": [],
        "confidence": dp.get("confidence", 0) if dp else 0,
        "critique": _try_generate_critique(tools_used or [], duration, turn_count),
    }
