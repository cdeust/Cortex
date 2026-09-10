"""Entity-merge cycle: collapse fuzzy-duplicate concept entities.

Two halves, cleanly split: ``core.entity_dedup`` plans the merge (pure, no I/O —
3-pass exact/MinHash-LSH/Jaro-Winkler) and ``store.merge_entities`` performs it
(atomic rewire). This consolidation cycle is the composition root that wires the
two together.

source: ADR-0359"""

from __future__ import annotations

import logging

from mcp_server.core.ablation import Mechanism, is_mechanism_disabled
from mcp_server.core.entity_dedup import deduplicate_entities
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)


def run_entity_merge_cycle(store: MemoryStore) -> dict:
    """Collapse near-duplicate concept entities into canonical survivors."""
    if is_mechanism_disabled(Mechanism.ENTITY_DEDUP):
        return {"merges_applied": 0, "ablated": True}
    try:
        entities = store.get_all_entities(min_heat=0.0)
        if len(entities) <= 1:
            return {"merges_applied": 0, "pairs_planned": 0}
        result = deduplicate_entities(entities)
        applied = _apply_merges(store, result.remap)
        return {"merges_applied": applied, "pairs_planned": len(result.remap)}
    except Exception:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.debug("Entity-merge cycle failed (non-fatal)")
        return {"merges_applied": 0, "pairs_planned": 0}


def _apply_merges(store: MemoryStore, remap: dict[str, str]) -> int:
    """Apply each alias→survivor merge.

    source: ADR-0359"""
    applied = 0
    for alias_key, survivor_key in remap.items():
        if not (alias_key.isdigit() and survivor_key.isdigit()):
            continue
        outcome = store.merge_entities(int(survivor_key), int(alias_key))
        if outcome.get("merged"):
            applied += 1
    return applied
