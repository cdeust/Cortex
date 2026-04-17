"""Decay cycle: cool all memories and entities based on elapsed time.

Includes domain-aware astrocyte metabolic modulation via tripartite synapse.

A3 writer refactor (Phase 3 step 7):
    When ``A3_LAZY_HEAT=true``, per-row memory decay is **not executed**
    here. The ``effective_heat()`` PL/pgSQL function (pg_schema.py)
    computes the decayed value at read time — the heat is a *function*,
    not a stored column update. Consequences:
      - ``compute_decay_updates`` is skipped
      - ``update_memories_heat_batch`` is skipped (I2: zero additional writers)
      - The emergence_tracker counter drops because there is no longer
        a per-row "decayed today" event — metric migrates to
        ``effective_heat`` probe samples (tracked separately, see #14 P3).

    Entity decay still runs (entities retain a stored heat column pre-D2)
    and metabolic modulation still runs for observability even when its
    heat updates are skipped (tripartite synapse territory state is still
    a valid observability signal even if we don't write back per-row).

    Flag=false path (legacy): unchanged. Full per-row decay write.

    Source: docs/program/phase-3-a3-migration-design.md §6 ("Decay
    cycle post-A3 — DELETE"). Adapted from hard-delete to flag-gated
    no-op to keep both paths valid for benchmark comparison per user
    directive (modify → benchmark → iterate).
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.decay_cycle import compute_decay_updates, compute_entity_decay
from mcp_server.core.tripartite_calcium import (
    apply_metabolic_modulation,
    compute_heterosynaptic_depression,
)
from mcp_server.core.tripartite_synapse import (
    AstrocyteTerritory,
    update_territory,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)


def run_decay_cycle(
    store: MemoryStore,
    settings: Any,
    memories: list[dict] | None = None,
) -> dict:
    """Apply heat decay to all active memories and entities.

    `memories` may be pre-loaded by the consolidate handler to avoid
    reloading the full store across stages (issue #13 — Feynman audit).

    Post-A3 (flag=true): memory heat decay is computed lazily in
    ``effective_heat()``; this function skips the per-row memory update.
    Entity decay and metabolic observability still run.
    """
    if memories is None:
        memories = store.get_all_memories_for_decay()

    a3_lazy = getattr(get_memory_settings(), "A3_LAZY_HEAT", False)

    if a3_lazy:
        # Post-A3: decay is lazy. No per-row memory write.
        # Entity heat still stored eagerly (D2 is out of scope for A3).
        entity_updates = _decay_entities(store, settings)
        return {
            "memories_decayed": 0,
            "metabolic_updates": 0,
            "entities_decayed": len(entity_updates),
            "total_memories": len(memories),
            "mode": "a3_lazy",
            "reason_for_zero": "lazy_decay_via_effective_heat",
        }

    # Pre-A3: legacy eager path.
    updates = compute_decay_updates(
        memories,
        decay_factor=settings.DECAY_FACTOR,
        importance_decay_factor=settings.IMPORTANCE_DECAY_FACTOR,
        emotional_decay_resistance=settings.EMOTIONAL_DECAY_RESISTANCE,
        cold_threshold=settings.COLD_THRESHOLD,
    )

    store.update_memories_heat_batch(updates)

    entity_updates = _decay_entities(store, settings)
    metabolic_updates = _apply_metabolic_modulation(
        store,
        settings,
        memories,
    )

    return {
        "memories_decayed": len(updates),
        "metabolic_updates": metabolic_updates,
        "entities_decayed": len(entity_updates),
        "total_memories": len(memories),
        "mode": "legacy_eager",
    }


def _decay_entities(
    store: MemoryStore,
    settings: Any,
) -> list[tuple[int, float]]:
    """Cool entity heat values."""
    entities = store.get_all_entities(min_heat=settings.COLD_THRESHOLD)
    entity_updates = compute_entity_decay(
        entities,
        decay_factor=0.98,
        cold_threshold=settings.COLD_THRESHOLD,
    )
    store.update_entities_heat_batch(entity_updates)
    return entity_updates


def _apply_metabolic_modulation(
    store: MemoryStore,
    settings: Any,
    memories: list[dict],
) -> int:
    """Apply tripartite synapse metabolic modulation per domain."""
    metabolic_updates = 0
    try:
        domain_groups = _group_by_domain(memories)
        for domain, mems in domain_groups.items():
            metabolic_updates += _modulate_domain(
                store,
                settings,
                domain,
                mems,
            )
    except Exception:
        pass
    return metabolic_updates


def _group_by_domain(memories: list[dict]) -> dict[str, list]:
    """Group memories by their domain field."""
    groups: dict[str, list] = {}
    for mem in memories:
        d = mem.get("domain", "default") or "default"
        groups.setdefault(d, []).append(mem)
    return groups


def _modulate_domain(
    store: MemoryStore,
    settings: Any,
    domain: str,
    mems: list[dict],
) -> int:
    """Apply heterosynaptic depression for a single domain territory."""
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
    apply_metabolic_modulation(settings.DECAY_FACTOR, territory.metabolic_rate)

    mem_heats = [m.get("heat", 0.5) for m in mems]
    adjustments = compute_heterosynaptic_depression(
        territory.calcium,
        mem_heats,
    )

    batch: list[tuple[int, float]] = []
    for mem, adj in zip(mems, adjustments):
        if adj < 0.99:
            new_heat = max(0.0, mem.get("heat", 0.5) * adj)
            batch.append((mem["id"], round(new_heat, 4)))
    return store.update_memories_heat_batch(batch)
