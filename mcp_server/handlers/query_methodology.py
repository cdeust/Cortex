"""Handler for the query_methodology tool — returns cognitive profile.

Enriched with thermodynamic memory: hot memories for the detected domain
and fired prospective triggers matching the current context are injected
into the response so session start has full cognitive + episodic context.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp_server.core.context_generator import generate_context
from mcp_server.core.domain_detector import detect_domain
from mcp_server.core.prospective import check_trigger
from mcp_server.infrastructure.profile_store import load_profiles

logger = logging.getLogger(__name__)

schema = {
    "description": "Returns the user's cognitive profile for the current domain. Pre-computed, <50ms. Use at session start for context injection.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "cwd": {"type": "string", "description": "Current working directory"},
            "project": {"type": "string", "description": "Project identifier"},
            "first_message": {
                "type": "string",
                "description": "First user message in session",
            },
        },
        "required": [],
    },
}

# ── Memory helpers (lazy import to avoid circular deps at module level) ──

_memory_store = None
_memory_available = None


def _try_get_memory_store():
    """Lazy-load memory store. Returns None if memory system isn't configured."""
    global _memory_store, _memory_available
    if _memory_available is False:
        return None
    if _memory_store is not None:
        return _memory_store
    try:
        from mcp_server.infrastructure.memory_config import get_memory_settings
        from mcp_server.infrastructure.memory_store import MemoryStore

        settings = get_memory_settings()
        _memory_store = MemoryStore(settings.DB_PATH, settings.EMBEDDING_DIM)
        _memory_available = True
        return _memory_store
    except Exception as e:
        logger.debug("Memory system not available: %s", e)
        _memory_available = False
        return None


def _normalize_tags(tags: Any) -> list:
    """Ensure tags is a list, parsing JSON strings if needed."""
    if isinstance(tags, list):
        return tags
    if isinstance(tags, str):
        try:
            return json.loads(tags)
        except (ValueError, TypeError):
            return []
    return []


def _get_hot_memories(
    domain: str, directory: str, limit: int = 10
) -> list[dict[str, Any]]:
    """Retrieve hottest memories for this domain/directory context."""
    store = _try_get_memory_store()
    if store is None:
        return []

    try:
        if domain:
            mems = store.get_memories_for_domain(domain, min_heat=0.1, limit=limit)
        elif directory:
            mems = store.get_memories_for_directory(directory, min_heat=0.1)[:limit]
        else:
            mems = store.get_hot_memories(min_heat=0.3, limit=limit)

        return [
            {
                "content": m["content"],
                "heat": round(m.get("heat", 0), 4),
                "domain": m.get("domain", ""),
                "tags": _normalize_tags(m.get("tags", [])),
                "importance": m.get("importance", 0.5),
                "created_at": m.get("created_at", ""),
            }
            for m in mems
        ]
    except Exception as e:
        logger.debug("Failed to retrieve hot memories: %s", e)
        return []


def _get_fired_triggers(directory: str, first_message: str) -> list[dict[str, Any]]:
    """Check all active prospective triggers against current context."""
    store = _try_get_memory_store()
    if store is None:
        return []

    try:
        active_triggers = store.get_active_prospective_memories()
        fired = []
        for trigger in active_triggers:
            if check_trigger(trigger, directory=directory, content=first_message):
                store.trigger_prospective_memory(trigger["id"])
                fired.append(
                    {
                        "content": trigger["content"],
                        "trigger_type": trigger["trigger_type"],
                        "trigger_condition": trigger["trigger_condition"],
                        "triggered_count": trigger.get("triggered_count", 0) + 1,
                    }
                )
        return fired
    except Exception as e:
        logger.debug("Failed to check prospective triggers: %s", e)
        return []


# ── Handler ──────────────────────────────────────────────────────────────


def _empty_response(domain=None, confidence=0, cold_start=False, context="") -> dict:
    return {
        "domain": domain,
        "confidence": confidence,
        "coldStart": cold_start,
        "context": context,
        "style": None,
        "entryPoints": [],
        "recurringPatterns": [],
        "toolPreferences": {},
        "blindSpots": [],
        "connectionBridges": [],
        "sessionCount": 0,
        "lastActive": None,
        "hotMemories": [],
        "firedTriggers": [],
    }


def _enrich_context_with_memories(
    context: str,
    hot_memories: list[dict[str, Any]],
    fired_triggers: list[dict[str, Any]],
) -> str:
    """Append memory and trigger summaries to the context string."""
    if not hot_memories and not fired_triggers:
        return context

    lines: list[str] = []
    if hot_memories:
        lines.append(f"\n\n## Active Memories ({len(hot_memories)} hot)")
        for mem in hot_memories[:5]:
            heat_bar = "█" * max(1, int(mem["heat"] * 10))
            lines.append(f"  [{heat_bar}] {mem['content'][:120]}")
    if fired_triggers:
        lines.append(f"\n## Triggered Reminders ({len(fired_triggers)})")
        for t in fired_triggers:
            lines.append(f"  ⚡ {t['content']}")

    return context + "\n".join(lines)


def _build_profile_response(
    domain_id: str,
    profile: dict[str, Any],
    detection: dict[str, Any],
    context: str,
    hot_memories: list[dict[str, Any]],
    fired_triggers: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the full response dict from a resolved profile."""
    return {
        "domain": domain_id,
        "confidence": profile.get("confidence") or detection.get("confidence", 0),
        "coldStart": False,
        "context": context,
        "style": profile.get("metacognitive"),
        "entryPoints": profile.get("entryPoints", []),
        "recurringPatterns": profile.get("recurringPatterns", []),
        "toolPreferences": profile.get("toolPreferences", {}),
        "blindSpots": profile.get("blindSpots", []),
        "connectionBridges": profile.get("connectionBridges", []),
        "sessionCount": profile.get("sessionCount", 0),
        "lastActive": profile.get("lastUpdated"),
        "alternativeDomains": detection.get("alternativeDomains", []),
        "hotMemories": hot_memories,
        "firedTriggers": fired_triggers,
    }


def _inject_memories(
    resp: dict,
    cwd: str,
    first_message: str,
    domain: str = "",
) -> dict:
    """Attach hot memories and fired triggers to a response dict."""
    resp["hotMemories"] = _get_hot_memories(domain, cwd)
    resp["firedTriggers"] = _get_fired_triggers(cwd, first_message)
    return resp


async def handler(args: dict | None = None) -> dict:
    args = args or {}
    cwd = args.get("cwd", "")
    first_message = args.get("first_message", "")

    profiles = load_profiles()
    detection = detect_domain(
        {"cwd": cwd, "project": args.get("project"), "first_message": first_message},
        profiles,
    )

    if detection.get("coldStart"):
        resp = _empty_response(
            cold_start=True,
            context=detection.get("context")
            or "No cognitive profile yet. Building one as we go.",
        )
        return _inject_memories(resp, cwd, first_message)

    domain_id = detection.get("domain")
    profile = profiles.get("domains", {}).get(domain_id) if domain_id else None
    hot_memories = _get_hot_memories(domain_id or "", cwd)
    fired_triggers = _get_fired_triggers(cwd, first_message)

    if not profile:
        resp = _empty_response(
            domain=domain_id,
            confidence=detection.get("confidence", 0),
            context=f'Domain "{domain_id}" detected but no profile built yet. Run rebuild_profiles to analyze session history.',
        )
        resp["hotMemories"] = hot_memories
        resp["firedTriggers"] = fired_triggers
        return resp

    context = generate_context(domain_id, profile)
    context = _enrich_context_with_memories(context, hot_memories, fired_triggers)

    return _build_profile_response(
        domain_id,
        profile,
        detection,
        context,
        hot_memories,
        fired_triggers,
    )
