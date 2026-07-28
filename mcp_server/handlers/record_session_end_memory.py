"""Memory-integration helpers for record_session_end.

Split out of record_session_end.py (Move 5: profile/session-log
bookkeeping is one concern, talking to the memory store is another —
also keeps record_session_end.py under the 500-line cap after M-D6
added lesson-candidate persistence, coding-standards.md §4.1).

Two write paths, both best-effort (a failure here must never fail
session-end):
  - ``_store_session_memory`` / ``_try_store_memory``: one episodic
    'session-summary' memory per session.
  - ``_build_lesson_candidate_args`` / ``_try_store_lesson_candidates``
    (M-D6, 7.6): one 'lesson-candidate' memory per non-empty
    self-critique top_suggestion — previously computed by
    generate_critique() and returned in the response, never persisted
    anywhere else (design §M-D6: "top_suggestions calculées puis
    perdues").
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

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
            # M-D2 (7.4): a single considered synthesis per session, not
            # noise — deliberate, never fold-prone.
            "write_class": "deliberate",
            "force": False,
        }
    except Exception as e:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.debug("Memory system not available for session recording: %s", e)
        _memory_available = False
        return None


async def _try_store_memory(memory_args: dict[str, Any] | None) -> bool:
    """Attempt to store session memory via the remember handler."""
    if memory_args is None:
        return False
    try:
        from mcp_server.handlers.remember import handler as remember_handler

        mem_result = await remember_handler(memory_args)
        return mem_result.get("stored", False)
    except Exception as e:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.debug("Failed to store session memory: %s", e)
        return False


def _build_lesson_candidate_args(
    suggestion: str,
    session_id: str,
    domain_id: str,
    cwd: str,
) -> dict[str, Any]:
    """Build remember-handler args for one self-critique suggestion.

    Precondition: `suggestion` is a non-empty, stripped string.
    Postcondition: returns args tagged 'lesson-candidate' + 'self-critique',
    source='self-critique', write_class='deliberate' (M-D2, 7.4) — a
    considered self-critique suggestion is NOT capture noise, so the
    write gate must never silently drop it the way it dropped
    memify_derive's templated facts before M-D2 existed (design §M-D6,
    "top_suggestions calculated then lost"). This is the fix for that:
    every non-empty suggestion becomes its own durable, recallable,
    ratable memory instead of a response field nobody persists.
    """
    return {
        "content": f"[self-critique, session {session_id}] {suggestion}",
        "tags": ["lesson-candidate", "self-critique"],
        "directory": cwd or "",
        "domain": domain_id,
        "source": "self-critique",
        "write_class": "deliberate",
        "force": False,
    }


async def _try_store_lesson_candidates(
    suggestions: list[str],
    session_id: str,
    domain_id: str,
    cwd: str,
) -> int:
    """Persist each non-empty top_suggestion as its own lesson-candidate memory.

    Precondition: `suggestions` is generate_critique()'s top_suggestions
    list (already capped to 5 by _collect_top_suggestions).
    Postcondition: returns the count of suggestions successfully stored.
    Never raises — best-effort, same contract as `_try_store_memory`: a
    self-critique persistence failure must not fail session-end.
    """
    from mcp_server.handlers.remember import handler as remember_handler

    stored = 0
    for suggestion in suggestions:
        text = (suggestion or "").strip()
        if not text:
            continue
        try:
            args = _build_lesson_candidate_args(text, session_id, domain_id, cwd)
            result = await remember_handler(args)
            if result.get("stored"):
                stored += 1
        except Exception as e:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
            logger.debug("Failed to store lesson-candidate suggestion: %s", e)
    return stored
