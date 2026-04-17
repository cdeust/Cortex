"""Decay cycle: entity heat decay only.

**A3 lazy-heat**: memory heat decay is computed at read time by
``effective_heat()`` in ``recall_memories()``. This eliminates the
per-row memory UPDATE that dominated consolidate runtime in darval's
v3.12.0 report. What remains here is *entity* decay (the
``entities.heat`` column still stores eager state until the D2
program lands) and metabolic-modulation observability on astrocyte
territories.

Source: docs/program/phase-3-a3-migration-design.md §6.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.decay_cycle import compute_entity_decay
from mcp_server.core.tripartite_calcium import apply_metabolic_modulation
from mcp_server.core.tripartite_synapse import (
    AstrocyteTerritory,
    update_territory,
)
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)


def run_decay_cycle(
    store: MemoryStore,
    settings: Any,
    memories: list[dict] | None = None,
) -> dict:
    """Decay entities and run metabolic observability.

    Memory heat decay is lazy — computed by ``effective_heat()`` on read.
    ``memories`` is kept in the signature for caller symmetry with
    pre-A3 but is only used to compute per-domain metabolic state.
    """
    if memories is None:
        memories = store.get_all_memories_for_decay()

    entity_updates = _decay_entities(store, settings)
    _update_metabolic_state(settings, memories)

    return {
        "memories_decayed": 0,
        "entities_decayed": len(entity_updates),
        "total_memories": len(memories),
        "reason_for_zero": "lazy_decay_via_effective_heat",
    }


def _decay_entities(
    store: MemoryStore,
    settings: Any,
) -> list[tuple[int, float]]:
    """Cool entity heat values. D2 (out of scope for A3) will make these lazy too."""
    entities = store.get_all_entities(min_heat=settings.COLD_THRESHOLD)
    entity_updates = compute_entity_decay(
        entities,
        decay_factor=0.98,
        cold_threshold=settings.COLD_THRESHOLD,
    )
    store.update_entities_heat_batch(entity_updates)
    return entity_updates


def _update_metabolic_state(settings: Any, memories: list[dict]) -> None:
    """Advance astrocyte territory state per domain (observability only).

    No heat writes: the A3 lazy path means territory state affects
    future reads only if wired into effective_heat, which is out of
    scope for this program (documented as open question in §5).
    """
    try:
        for domain, mems in _group_by_domain(memories).items():
            territory = AstrocyteTerritory(
                territory_id=domain,
                domain=domain,
                total_activity=sum(m.get("access_count", 0) for m in mems),
            )
            territory = update_territory(
                territory,
                synaptic_events=len(mems),
                hours_elapsed=1.0,
            )
            apply_metabolic_modulation(
                settings.DECAY_FACTOR, territory.metabolic_rate
            )
    except Exception as exc:
        logger.debug("Metabolic observability update failed: %s", exc)


def _group_by_domain(memories: list[dict]) -> dict[str, list]:
    groups: dict[str, list] = {}
    for mem in memories:
        d = mem.get("domain", "default") or "default"
        groups.setdefault(d, []).append(mem)
    return groups
