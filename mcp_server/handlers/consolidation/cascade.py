"""Cascade cycle: advance memory consolidation stages.

Memories progress through: LABILE -> EARLY_LTP -> LATE_LTP -> CONSOLIDATED.
"""

from __future__ import annotations

import logging

from mcp_server.core import cascade as cascade_core
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)

_ADVANCEABLE_STAGES = ["labile", "early_ltp", "late_ltp", "reconsolidating"]


def run_cascade_advancement(store: MemoryStore) -> dict:
    """Advance memory consolidation stages based on time and conditions."""
    try:
        advanced = 0
        stages_before: dict[str, int] = {}
        stages_after: dict[str, int] = {}

        for stage_name in _ADVANCEABLE_STAGES:
            memories = store.get_memories_by_stage(stage_name, limit=200)
            stages_before[stage_name] = len(memories)

            for mem in memories:
                did_advance = _advance_memory(store, mem, stage_name)
                if did_advance:
                    advanced += 1
                    next_stage = _get_next_stage(mem, stage_name)
                    stages_after[next_stage] = stages_after.get(next_stage, 0) + 1

        return {
            "advanced": advanced,
            "stages_before": stages_before,
            "stages_after": stages_after,
        }
    except Exception:
        logger.debug("Cascade advancement failed (non-fatal)")
        return {"advanced": 0}


def _advance_memory(
    store: MemoryStore,
    mem: dict,
    stage_name: str,
) -> bool:
    """Check and advance a single memory's consolidation stage."""
    hours = mem.get("hours_in_stage", 0.0) + 1.0

    ready, next_stage, _ = cascade_core.compute_advancement_readiness(
        stage_name,
        hours,
        dopamine_level=1.0,
        replay_count=mem.get("replay_count", 0),
        schema_match=mem.get("schema_match_score", 0.0),
        importance=mem.get("importance", 0.5),
    )

    if ready and next_stage != stage_name:
        store.update_memory_consolidation(
            mem["id"],
            next_stage,
            0.0,
            mem.get("replay_count", 0),
            mem.get("hippocampal_dependency", 1.0),
        )
        return True

    store.update_memory_consolidation(
        mem["id"],
        stage_name,
        hours,
        mem.get("replay_count", 0),
        mem.get("hippocampal_dependency", 1.0),
    )
    return False


def _get_next_stage(mem: dict, current_stage: str) -> str:
    """Compute the next stage for stats tracking."""
    hours = mem.get("hours_in_stage", 0.0) + 1.0
    _, next_stage, _ = cascade_core.compute_advancement_readiness(
        current_stage,
        hours,
        dopamine_level=1.0,
        replay_count=mem.get("replay_count", 0),
        schema_match=mem.get("schema_match_score", 0.0),
        importance=mem.get("importance", 0.5),
    )
    return next_stage
