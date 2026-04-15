"""Homeostatic cycle: synaptic scaling and BCM threshold updates.

Prevents runaway heat distributions by scaling memory heats toward a target mean.
"""

from __future__ import annotations

import logging

from mcp_server.core import homeostatic_health, homeostatic_plasticity
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)


def run_homeostatic_cycle(
    store: MemoryStore,
    memories: list[dict] | None = None,
) -> dict:
    """Apply synaptic scaling and BCM threshold updates.

    Surfaces failures explicitly via the returned dict (issue #13, darval):
    previous versions swallowed exceptions with logger.debug and returned
    {"health_score": 0.0} with no error field, which was indistinguishable
    from a legitimate empty-store run.

    `memories` may be pre-loaded by the consolidate handler to avoid
    reloading the full store.
    """
    try:
        if memories is None:
            memories = store.get_all_memories_for_decay()
        if not memories:
            return {
                "scaling_applied": False,
                "health_score": None,
                "reason": "no_memories",
                "memories_scanned": 0,
            }

        heats = [m.get("heat", 0.5) for m in memories]
        health = homeostatic_health.compute_distribution_health(
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
            "memories_scanned": len(memories),
        }
    except Exception as exc:
        logger.warning("Homeostatic cycle failed: %s", exc, exc_info=True)
        return {
            "scaling_applied": False,
            "health_score": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


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
