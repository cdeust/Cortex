"""Store-derived signal readers consumed by pg_recall's orchestration stages.

Split from pg_recall.py (continuing the two documented seams cut at #368 —
pg_recall_weights.py / pg_recall_assembly.py — with a third) to bring
pg_recall.py under this repo's local 300-line file cap and 40-line method
cap (CLAUDE.md § Code Style; a tightening of coding-standards.md §4.1/§4.2).

Every reader here is defensive: it duck-types against an optional method on
``store`` and returns the neutral "no signal" value (``EMPTY_GOAL`` / ``None``)
rather than fabricating one when the method is absent or the read fails —
per the zetetic source-discipline rule (coding-standards.md §8).
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import goal_maintenance
from mcp_server.core.titans_memory import TitansMemory
from mcp_server.observability import silent_failure

# Singleton Titans memory module (persists across recalls within a session)
_titans: TitansMemory | None = None


def _get_titans() -> TitansMemory:
    global _titans
    if _titans is None:
        _titans = TitansMemory()
    return _titans


def _get_active_goal(store: Any) -> Any:
    """Promote the store's active prospective triggers into a sustained goal (A3).

    Defensive reader mirroring ``_get_user_mood``: looks for
    ``get_active_prospective_memories()`` on the store (the same method
    query_methodology uses to fire triggers) and promotes the returned trigger
    dicts into a ``goal_maintenance.GoalVector`` — the held task-set that biases
    this recall toward goal-relevant memories (Miller & Cohen 2001).

    Returns ``goal_maintenance.EMPTY_GOAL`` (inactive → identity re-weight) when
    the store is None, lacks the reader, has no active triggers, or the read
    fails. Per the source-discipline rule we never fabricate a goal signal.
    """

    if store is None or not hasattr(store, "get_active_prospective_memories"):
        return goal_maintenance.EMPTY_GOAL
    try:
        triggers = store.get_active_prospective_memories()
        return goal_maintenance.build_goal_from_triggers(triggers)
    except Exception as exc:  # noqa: BLE001 — non-load-bearing; absence is fine
        silent_failure.note("pg_recall.active_goal", exc)
        return goal_maintenance.EMPTY_GOAL


def _get_user_mood(store: Any) -> float | None:
    """Return the user's session-level mood in [-1, +1], or None if absent.

    Looks for an explicit ``get_user_mood()`` method on the store. There is
    no such method in the current ``PgMemoryStore`` (April 2026), so this
    helper returns ``None`` and the MOOD_CONGRUENT_RERANK stage no-ops —
    per the zetetic source-discipline rule we do NOT fabricate a mood signal.
    When an upstream emotion classifier or manual checkpoint annotation
    populates a mood store, expose ``get_user_mood()`` and this helper
    will start returning real values without further wiring changes.
    """
    if store is None:
        return None
    if not hasattr(store, "get_user_mood"):
        return None
    try:
        v = store.get_user_mood()
    except Exception as exc:  # noqa: BLE001 — non-load-bearing; absence is fine
        silent_failure.note("pg_recall.user_mood", exc)
        return None
    if v is None:
        return None
    try:
        return max(-1.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return None
