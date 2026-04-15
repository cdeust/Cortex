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

# Source: issue #13 — cascade previously wrote a heartbeat UPDATE on
# EVERY scanned memory (~2000) even when nothing advanced. Below this
# delta, the hours_in_stage change is noise and the write is waste.
_HEARTBEAT_SKIP_HOURS = 1.0

# Source: issue #13 — the 503-transition payload darval reported is
# redundant with the stage_transitions table and inflates the MCP
# response. Surface a preview + count instead.
_TRANSITION_PREVIEW_CAP = 50


def run_cascade_advancement(store: MemoryStore) -> dict:
    """Advance memory consolidation stages based on real elapsed time.

    Skips no-op heartbeat UPDATEs (|Δhours| < _HEARTBEAT_SKIP_HOURS),
    batches stage_transitions INSERTs into one statement, and caps the
    response payload at `transitions_preview` (first N) + total count.
    """
    try:
        transitions: list[dict] = []
        heartbeats_written = 0
        heartbeats_skipped = 0
        scanned = 0
        now = datetime.now(timezone.utc)

        for stage_name in _ADVANCEABLE_STAGES:
            memories = store.get_memories_by_stage(stage_name, limit=500)
            scanned += len(memories)

            for mem in memories:
                result, heartbeat = _try_advance(store, mem, stage_name, now)
                if result:
                    transitions.append(result)
                if heartbeat == "written":
                    heartbeats_written += 1
                elif heartbeat == "skipped":
                    heartbeats_skipped += 1

        store.insert_stage_transitions_batch(transitions)

        return {
            "advanced": len(transitions),
            "scanned": scanned,
            "heartbeats_written": heartbeats_written,
            "heartbeats_skipped": heartbeats_skipped,
            "transitions_count": len(transitions),
            "transitions_preview": transitions[:_TRANSITION_PREVIEW_CAP],
        }
    except Exception as exc:
        logger.warning("Cascade advancement failed: %s", exc, exc_info=True)
        return {
            "advanced": 0,
            "scanned": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }


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
) -> tuple[dict | None, str]:
    """Check and advance a single memory.

    Returns (transition_or_None, heartbeat_status) where heartbeat_status
    is one of "written", "skipped", "transition".
    """
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
        return (
            {
                "memory_id": mem["id"],
                "from_stage": stage_name,
                "to_stage": next_stage,
                "hours_in_prev": round(hours, 2),
            },
            "transition",
        )

    # Not advancing: only write a heartbeat if the hours delta is
    # large enough to be informative. Below _HEARTBEAT_SKIP_HOURS the
    # change is noise and the write is wasted fsync amplification
    # (issue #13, Feinstein audit of darval's 66K-store run).
    prev_hours = float(mem.get("hours_in_stage", 0.0) or 0.0)
    if abs(hours - prev_hours) < _HEARTBEAT_SKIP_HOURS:
        return None, "skipped"

    store.update_memory_consolidation(
        mem["id"],
        stage_name,
        round(hours, 2),
        mem.get("replay_count", 0),
        mem.get("hippocampal_dependency", 1.0),
    )
    return None, "written"


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
