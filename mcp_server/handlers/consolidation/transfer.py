"""Two-stage transfer: hippocampal -> cortical for replay-eligible memories.

Reduces hippocampal dependency for well-replayed memories, enabling
cortical independence (McClelland 1995).
"""

from __future__ import annotations

import logging

from mcp_server.core import two_stage_model

# Canonical thresholds — defined once in core.two_stage_transfer (its
# comment forbids redefinition so the copies cannot drift); imported here
# exactly as core.two_stage_model does.
from mcp_server.core.two_stage_transfer import (
    _HIPPOCAMPAL_RELEASE_THRESHOLD,
    _MIN_REPLAYS_FOR_TRANSFER,
)
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)

_ELIGIBLE_STAGES = ["early_ltp", "late_ltp", "consolidated"]


def run_two_stage_transfer(store: MemoryStore) -> dict:
    """Run hippocampal -> cortical transfer for replay-eligible memories."""
    try:
        eligible = _collect_eligible(store)
        transferred = _transfer_eligible(store, eligible)
        metrics = two_stage_model.compute_transfer_metrics(eligible)
        metrics["transferred_this_cycle"] = transferred
    except Exception:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.debug("Two-stage transfer failed (non-fatal)")
        return {"transferred_this_cycle": 0}
    else:
        return metrics


def _collect_eligible(store: MemoryStore) -> list[dict]:
    """Collect memories eligible for hippocampal -> cortical transfer."""
    eligible = []
    for stage in _ELIGIBLE_STAGES:
        mems = store.get_memories_by_stage(stage, limit=100)
        for m in mems:
            if m.get("replay_count", 0) >= _MIN_REPLAYS_FOR_TRANSFER:
                eligible.append(m)
    return eligible


def _transfer_eligible(
    store: MemoryStore,
    eligible: list[dict],
) -> int:
    """Reduce hippocampal dependency for eligible memories."""
    count = 0
    for mem in eligible:
        old_dep = mem.get("hippocampal_dependency", 1.0)
        if old_dep <= _HIPPOCAMPAL_RELEASE_THRESHOLD:
            continue

        new_dep = two_stage_model.update_hippocampal_dependency(
            old_dep,
            mem.get("replay_count", 0),
            schema_match=mem.get("schema_match_score", 0.0),
            importance=mem.get("importance", 0.5),
        )

        if new_dep < old_dep:
            store.update_memory_consolidation(
                mem["id"],
                mem.get("consolidation_stage", "early_ltp"),
                mem.get("hours_in_stage", 0.0),
                mem.get("replay_count", 0),
                new_dep,
            )
            count += 1
    return count
