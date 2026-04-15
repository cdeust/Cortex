"""Plasticity cycle: Hebbian LTP/LTD on knowledge graph edges.

Strengthens co-accessed entity relationships and weakens unused ones
using BCM sliding threshold dynamics.
"""

from __future__ import annotations

import logging

from mcp_server.core.synaptic_plasticity import apply_hebbian_update
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)


def run_plasticity_cycle(
    store: MemoryStore,
    memories: list[dict] | None = None,
) -> dict:
    """Apply Hebbian LTP/LTD to knowledge graph edges.

    `memories` may be pre-loaded by the consolidate handler (Phase B of
    issue #13). When not provided, falls back to a broader hot-memory
    window than before to avoid the co-access starvation documented in
    the Feinstein/Feynman audit of darval's 66K run (previous limit=50
    across 10,770 entities → 99.95% LTD was distribution collapse, not
    plasticity).
    """
    try:
        entities = store.get_all_entities(min_heat=0.0)
        relationships = store.get_all_relationships()

        if not entities or not relationships:
            return {
                "ltp": 0,
                "ltd": 0,
                "edges_updated": 0,
                "co_access_pairs": 0,
                "memories_sampled": 0,
            }

        activities, thresholds = _build_entity_maps(entities)
        sample = _select_co_access_sample(store, memories)
        co_accessed = _find_co_accessed_pairs(sample, entities)
        edge_dicts = _format_edges(relationships)

        results = apply_hebbian_update(
            edge_dicts,
            co_accessed,
            activities,
            thresholds,
            hours_since_last_update=1.0,
        )

        ltp_count, ltd_count = _apply_updates(store, results)
        return {
            "ltp": ltp_count,
            "ltd": ltd_count,
            "edges_updated": ltp_count + ltd_count,
            "co_access_pairs": len(co_accessed),
            "memories_sampled": len(sample),
        }
    except Exception as exc:
        logger.warning("Plasticity cycle failed: %s", exc, exc_info=True)
        return {
            "ltp": 0,
            "ltd": 0,
            "edges_updated": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }


# Source: issue #13 — the previous limit=50 sampled ~0.5% of a 10k-
# entity store which collapsed the co-access set. 2000 gives an order-
# of-magnitude better sample while keeping the subsequent O(N_mem × N_ent)
# substring loop under ~25M ops on darval's store size.
_CO_ACCESS_SAMPLE_CAP = 2000


def _select_co_access_sample(
    store: MemoryStore,
    memories: list[dict] | None,
) -> list[dict]:
    """Select the memory sample used to infer entity co-access.

    Prefers the consolidation-scoped list (filtered to hot memories)
    when available; otherwise falls back to store.get_hot_memories with
    a larger cap than the pre-#13 value.
    """
    if memories is None:
        return store.get_hot_memories(min_heat=0.1, limit=_CO_ACCESS_SAMPLE_CAP)
    hot = [m for m in memories if float(m.get("heat", 0.0)) >= 0.1]
    if len(hot) <= _CO_ACCESS_SAMPLE_CAP:
        return hot
    hot.sort(key=lambda m: float(m.get("heat", 0.0)), reverse=True)
    return hot[:_CO_ACCESS_SAMPLE_CAP]


def _build_entity_maps(
    entities: list[dict],
) -> tuple[dict[int, float], dict[int, float]]:
    """Build activity and BCM threshold maps from entity data."""
    activities: dict[int, float] = {}
    thresholds: dict[int, float] = {}
    for ent in entities:
        eid = ent["id"]
        heat = ent.get("heat", 0.5)
        access = ent.get("access_count", 0)
        activities[eid] = min(1.0, heat + access * 0.01)
        thresholds[eid] = 0.3 + heat * 0.4
    return activities, thresholds


def _find_co_accessed_pairs(
    sample: list[dict],
    entities: list[dict],
) -> set[tuple[int, int]]:
    """Determine co-accessed entity pairs from a memory sample.

    Caller selects the sample (see `_select_co_access_sample`). Uses a
    precomputed (name_lower, id) list so the inner loop is a plain
    Python substring check without repeated `.lower()` calls.
    """
    index = [
        (e["name"].lower(), e["id"])
        for e in entities
        if e.get("name") and e.get("id") is not None
    ]
    co_accessed: set[tuple[int, int]] = set()

    for mem in sample:
        content_lower = (mem.get("content") or "").lower()
        if not content_lower:
            continue
        mem_entities = [eid for (name, eid) in index if name in content_lower]
        n = len(mem_entities)
        if n < 2:
            continue
        for i in range(n):
            a = mem_entities[i]
            for j in range(i + 1, n):
                b = mem_entities[j]
                co_accessed.add((a, b) if a < b else (b, a))

    return co_accessed


def _format_edges(relationships: list[dict]) -> list[dict]:
    """Format relationship rows into edge dicts for Hebbian update."""
    return [
        {
            "id": r["id"],
            "source_entity_id": r["source_entity_id"],
            "target_entity_id": r["target_entity_id"],
            "weight": r.get("weight", 1.0),
        }
        for r in relationships
    ]


def _apply_updates(
    store: MemoryStore,
    results: list[dict],
) -> tuple[int, int]:
    """Apply Hebbian weight updates via a single batched UPDATE.

    Source: issue #13 — plasticity previously ran one UPDATE per edge
    inside a loop. Batched path collapses 30k+ round-trips into one.
    """
    batch: list[tuple[int, float]] = []
    ltp_count = 0
    ltd_count = 0
    for r in results:
        if r["action"] == "none":
            continue
        batch.append((r["id"], r["weight"]))
        if r["action"] == "ltp":
            ltp_count += 1
        else:
            ltd_count += 1
    store.update_relationships_weight_batch(batch)
    return ltp_count, ltd_count
