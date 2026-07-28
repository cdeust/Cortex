"""Consolidation cycle: dopaminergic active forgetting (two independent circuits).

Composition root wiring ``core.active_forgetting`` (pure decisions) to the PG
store (newer-neighbor search + reversible effects). It runs AFTER the deep-sleep
replay pass so memories replayed this cycle count as sleep-protected
(``recently_active``) and are exempt from the ongoing forgetting signal — sleep
inhibits the Rac1 forgetting circuit (Davis & Zhong 2017, Neuron 95:490-503).

Per active memory that is neither pinned nor replayed this cycle:

  - ``chronic`` = the core ``chronic_interference`` over the NEWER overlapping
    neighbours: a REDUNDANCY-GATED excess noisy-OR that counts only genuine
    near-duplicates (sim ≥ τ_dup = curation.MERGE_THRESHOLD), excluding the ~0.5
    background band of 384-dim embeddings. This is the saturation fix — a plain
    noisy-OR over the 10 nearest newer neighbours saturated to ≈1.0 for 99.6% of
    memories and marked 46% of the corpus stale in one cycle. The gating lives in
    pure core (the store returns raw per-neighbour similarities), unit-testable
    without a database (SRP).

  - ``accum`` = the leaky integrator over cycles: ``λ·accum_{t-1} + chronic ×
    stage_vulnerability × cortical_availability(hippocampal_dependency)``.
    Permanent forgetting requires *sustained* pressure (accum ≥ Θ_accum),
    faithful to the gradual Rac1/cofilin erosion; sleep-protected cycles add 0
    and let the accumulator leak. The prior accumulator is read from the row
    and the new value is written back EVERY cycle. The cortical-availability
    factor is CLS-B gate C (McClelland 1995 two-stage transfer, see
    ``core.active_forgetting.cortical_availability``): a still hippocampally-
    dependent memory accumulates this pressure more slowly — bounded and
    never zero, so this is a SOFT modulation of resistance, not a veto.

  - the acute interferer = the strongest newer neighbor (``acute_overlap``) and
    its age (``acute_age_hours``), feeding the stage-independent transient DAMB
    block (Sabandal, Berry & Davis 2021, Nature 591:426-430).

Effects, both reversible (the two circuits read disjoint signals and never
chain — Sabandal 2021 tested and rejected transient→permanent conversion):

  - permanent (Rac1) → ``mark_memory_stale(True)``: the row persists as a
    residual engram, reinstated when the trace is reactivated.
  - transient (DAMB) → ``heat × (1 - acute_overlap)``: retrieval suppression
    whose magnitude rides the *measured* interferer salience. No biological
    rate law exists for this magnitude at the hours/days timescale and the
    salience effect is ordinal only (Berry, Phan & Davis 2018, PMC6239218), so
    the suppression is scaled by the interferer overlap itself rather than an
    invented constant; heat recovers on re-access.

Ablation-gated by ``Mechanism.ACTIVE_FORGETTING``.
"""

from __future__ import annotations

import logging
from typing import Iterable

from mcp_server.core.ablation import Mechanism, is_mechanism_disabled
from mcp_server.core.active_forgetting import (
    chronic_interference,
    is_permanent_forgetting,
    is_transient_forgetting,
    update_pressure_accum,
)
from mcp_server.infrastructure.memory_store import MemoryStore

logger = logging.getLogger(__name__)

# Newer-neighbor fan-out for the chronic aggregate. Bounds I/O only: the gated
# noisy-OR counts only near-duplicates, so this caps how much of a long similar-
# neighbor tail is scanned — it is NOT a biological rate constant. Matches the
# store's default KNN width.
# source: I/O bound; mirrors search_vectors default top_k (pg_store.py)
NEIGHBOR_K = 10


def run_forgetting_cycle(
    store: MemoryStore,
    recently_active_ids: set[int],
) -> dict:
    """Run the two-circuit active-forgetting pass over all active memories.

    Streams the corpus in bounded chunks (constant memory) and evaluates each
    memory against its newer overlapping neighbors. ``recently_active_ids`` are
    the memories replayed by the deep-sleep pass this cycle (sleep-protected).
    """
    if is_mechanism_disabled(Mechanism.ACTIVE_FORGETTING):
        return {"scanned": 0, "permanent": 0, "transient": 0, "ablated": True}
    if not hasattr(store, "search_newer_neighbors"):
        # Cowork/SQLite fallback does not implement the newer-neighbor query;
        # active forgetting is a production (PostgreSQL) deep-cycle mechanism.
        return {
            "scanned": 0,
            "permanent": 0,
            "transient": 0,
            "skipped": "unsupported_store",
        }

    counts = {"scanned": 0, "permanent": 0, "transient": 0}
    if hasattr(store, "iter_memories_for_decay"):
        chunks: Iterable[list[dict]] = store.iter_memories_for_decay()
    else:
        chunks = [store.get_all_memories_for_decay()]

    for chunk in chunks:
        for mem in chunk:
            counts["scanned"] += 1
            try:
                effect = _evaluate_memory(store, mem, recently_active_ids)
            except Exception:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
                logger.debug("Forgetting eval failed for memory %s", mem.get("id"))
                continue
            if effect in ("permanent", "transient"):
                counts[effect] += 1
    return counts


def _evaluate_memory(
    store: MemoryStore,
    mem: dict,
    recently_active_ids: set[int],
) -> str:
    """Decide and apply the forgetting effect for one memory.

    Returns ``"permanent"``, ``"transient"``, or ``"retain"``. The permanent
    (stale) effect subsumes the transient (heat) effect, so once a memory is
    marked stale the redundant heat write is skipped — the independence of the
    two circuits is preserved at the DECISION level (disjoint signals), not by
    forcing two writes on the same row. The leaky-integrator accumulator is
    advanced and persisted EVERY cycle (including leak-down) so sustained
    pressure carries across cycles.
    """
    embedding = mem.get("embedding")
    if not embedding:
        return "retain"

    memory_id = int(mem["id"])
    created_at = mem.get("created_at")
    # A row without created_at cannot have "newer" neighbors — the SQL
    # comparison against NULL matched no rows; make that explicit.
    neighbors = (
        store.search_newer_neighbors(
            embedding, str(created_at), memory_id, top_k=NEIGHBOR_K
        )
        if created_at is not None
        else []
    )
    chronic = chronic_interference(sim for sim, _ in neighbors)
    acute_overlap, acute_age_hours = neighbors[0] if neighbors else (0.0, float("inf"))

    stage = mem.get("consolidation_stage") or "labile"
    heat = float(mem.get("heat", 0.0))
    is_pinned = bool(mem.get("is_protected")) or heat >= 1.0
    recently_active = memory_id in recently_active_ids

    prev_accum = float(mem.get("forgetting_pressure_accum") or 0.0)
    # CLS-B gate C: default 1.0 (fully hippocampal) when absent, matching the
    # production DEFAULT for hippocampal_dependency — an unset value must
    # apply the STRONGEST modulation, not the weakest, or an unmigrated row
    # would silently forget at the fully-cortical rate. `or` cannot be used
    # for this fallback: 0.0 (a legitimate, fully cortical value) is falsy in
    # Python and would be wrongly overridden to 1.0 — hence the explicit
    # ``is None`` check.
    raw_dependency = mem.get("hippocampal_dependency")
    hippocampal_dependency = 1.0 if raw_dependency is None else float(raw_dependency)
    accum = update_pressure_accum(
        prev_accum,
        stage,
        chronic,
        recently_active,
        hippocampal_dependency=hippocampal_dependency,
    )
    store.update_forgetting_pressure_accum(memory_id, accum)

    if is_permanent_forgetting(accum, is_pinned, recently_active):
        store.mark_memory_stale(memory_id, True)
        return "permanent"
    if is_transient_forgetting(
        acute_overlap, acute_age_hours, is_pinned, recently_active
    ):
        store.update_memory_heat(memory_id, heat * (1.0 - acute_overlap))
        return "transient"
    return "retain"
