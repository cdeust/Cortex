"""Cascade cycle: advance memory consolidation stages.

Memories progress through: LABILE -> EARLY_LTP -> LATE_LTP -> CONSOLIDATED.
Uses real elapsed time from stage_entered_at to compute hours_in_stage.
Logs every transition to stage_transitions table for timeline visualization.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from mcp_server.core.cascade_advancement import compute_advancement_readiness
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)

_ADVANCEABLE_STAGES = ["labile", "early_ltp", "late_ltp", "reconsolidating"]


def run_cascade_advancement(store: MemoryStore) -> dict:
    """Advance memory consolidation stages based on real elapsed time."""
    try:
        advanced = 0
        transitions: list[dict] = []
        now = datetime.now(timezone.utc)

        for stage_name in _ADVANCEABLE_STAGES:
            memories = store.get_memories_by_stage(stage_name, limit=500)

            for mem in memories:
                result = _try_advance(store, mem, stage_name, now)
                if result:
                    advanced += 1
                    transitions.append(result)

        # Log transitions to stage_transitions table
        for t in transitions:
            _log_transition(store, t)

        return {
            "advanced": advanced,
            "transitions": transitions,
        }
    except Exception as e:
        logger.debug("Cascade advancement failed: %s", e)
        return {"advanced": 0, "transitions": []}


def _compute_real_hours(mem: dict, now: datetime) -> float:
    """Compute real hours since the memory entered its current stage."""
    stage_entered = mem.get("stage_entered_at")
    if stage_entered:
        if isinstance(stage_entered, str):
            try:
                stage_entered = datetime.fromisoformat(stage_entered)
            except (ValueError, TypeError):
                stage_entered = None
        if stage_entered:
            if stage_entered.tzinfo is None:
                stage_entered = stage_entered.replace(tzinfo=timezone.utc)
            delta = now - stage_entered
            return max(0.0, delta.total_seconds() / 3600.0)

    # Fallback: use created_at
    created = mem.get("created_at")
    if created:
        if isinstance(created, str):
            try:
                created = datetime.fromisoformat(created)
            except (ValueError, TypeError):
                return mem.get("hours_in_stage", 0.0)
        if created:
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            delta = now - created
            return max(0.0, delta.total_seconds() / 3600.0)

    return mem.get("hours_in_stage", 0.0)


_MIN_DWELL = {
    "labile": 1.0,
    "early_ltp": 6.0,
    "late_ltp": 24.0,
    "consolidated": float("inf"),
    "reconsolidating": 6.0,
}


def _try_advance(
    store: MemoryStore,
    mem: dict,
    stage_name: str,
    now: datetime,
) -> dict | None:
    """Check and advance a single memory. Returns transition info or None."""
    hours = _compute_real_hours(mem, now)

    ready, next_stage, _ = compute_advancement_readiness(
        stage_name,
        hours,
        dopamine_level=1.0,
        replay_count=mem.get("replay_count", 0),
        schema_match=mem.get("schema_match_score", 0.0),
        importance=mem.get("importance", 0.5),
    )

    if ready and next_stage != stage_name:
        # Compute stage_entered_at for the new stage:
        # For backfilled memories with real timestamps, account for the time
        # they would have spent in the previous stage (min_dwell hours).
        dwell = _MIN_DWELL.get(stage_name, 1.0)
        remaining_hours = max(0.0, hours - dwell)
        from datetime import timedelta

        new_entered = now - timedelta(hours=remaining_hours)

        store.update_memory_consolidation(
            mem["id"],
            next_stage,
            round(remaining_hours, 2),
            mem.get("replay_count", 0),
            mem.get("hippocampal_dependency", 1.0),
        )
        _update_stage_entered(store, mem["id"], new_entered)
        return {
            "memory_id": mem["id"],
            "from_stage": stage_name,
            "to_stage": next_stage,
            "hours_in_prev": round(hours, 2),
        }

    # Not ready: just update hours_in_stage with real value
    store.update_memory_consolidation(
        mem["id"],
        stage_name,
        round(hours, 2),
        mem.get("replay_count", 0),
        mem.get("hippocampal_dependency", 1.0),
    )
    return None


def _update_stage_entered(store: MemoryStore, memory_id: int, now: datetime) -> None:
    """Set stage_entered_at to current time after a transition."""
    try:
        store._conn.execute(
            "UPDATE memories SET stage_entered_at = %s WHERE id = %s",
            (now, memory_id),
        )
        store._conn.commit()
    except Exception:
        pass


def _log_transition(store: MemoryStore, transition: dict) -> None:
    """Log a stage transition to the stage_transitions table."""
    try:
        store._conn.execute(
            "INSERT INTO stage_transitions "
            "(memory_id, from_stage, to_stage, hours_in_prev_stage, trigger) "
            "VALUES (%s, %s, %s, %s, %s)",
            (
                transition["memory_id"],
                transition["from_stage"],
                transition["to_stage"],
                transition["hours_in_prev"],
                "cascade",
            ),
        )
        store._conn.commit()
    except Exception as e:
        logger.debug("Failed to log transition: %s", e)
