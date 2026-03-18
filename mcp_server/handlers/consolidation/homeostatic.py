"""Homeostatic cycle: synaptic scaling and BCM threshold updates.

Prevents runaway heat distributions by scaling memory heats toward a target mean.
"""

from __future__ import annotations

import logging

from mcp_server.core import homeostatic_plasticity
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)


def run_homeostatic_cycle(store: MemoryStore) -> dict:
    """Apply synaptic scaling and BCM threshold updates."""
    try:
        memories = store.get_all_memories_for_decay()
        if not memories:
            return {"scaling_applied": False, "health_score": 0.0}

        heats = [m.get("heat", 0.5) for m in memories]
        health = homeostatic_plasticity.compute_distribution_health(
            heats,
            target_mean=0.4,
        )

        scaling_applied = _maybe_apply_scaling(store, memories, heats, health)

        return {
            "scaling_applied": scaling_applied,
            "health_score": health["health_score"],
            "mean_heat": health["mean"],
            "std_heat": health["std"],
            "bimodality": health["bimodality_coefficient"],
        }
    except Exception:
        logger.debug("Homeostatic cycle failed (non-fatal)")
        return {"scaling_applied": False, "health_score": 0.0}


def _maybe_apply_scaling(
    store: MemoryStore,
    memories: list[dict],
    heats: list[float],
    health: dict,
) -> bool:
    """Apply synaptic scaling if distribution is unhealthy."""
    if health["health_score"] >= 0.6:
        return False

    factor = homeostatic_plasticity.compute_scaling_factor(
        health["mean"],
        target_heat=0.4,
    )
    if abs(factor - 1.0) <= 0.005:
        return False

    scaled = homeostatic_plasticity.apply_synaptic_scaling(heats, factor)
    for mem, new_heat in zip(memories, scaled):
        if abs(new_heat - mem.get("heat", 0)) > 0.001:
            store.update_memory_heat(mem["id"], round(new_heat, 4))
    return True
