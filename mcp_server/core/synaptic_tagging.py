"""Synaptic Tagging & Capture (STC) — retroactive memory strengthening.

Implements the STC model for retroactive promotion of weak memories by
strong events that share entities (proxy for spatial proximity on the
dendritic tree).

References
----------
- Frey & Morris (1997), Nature 385:533-536:
  Discovered that weak tetanization (E-LTP) sets a transient "synaptic tag"
  at activated synapses. If a strong tetanization (L-LTP) occurs at nearby
  synapses within ~90 minutes, plasticity-related proteins (PRPs) produced
  by the strong event are "captured" by the tagged synapses, converting
  E-LTP to L-LTP. The tag is necessary but not sufficient — PRPs are
  required for consolidation.

- Clopath et al. (2008), PLoS Comp Biol 4:e1000248:
  Formalized the STC model computationally. Key elements:
  (a) Strong stimulation triggers both a tag and PRP synthesis.
  (b) Weak stimulation triggers only a tag (no local PRP synthesis).
  (c) Tags decay exponentially with time constant ~90 min.
  (d) Capture occurs when PRPs diffuse to tagged synapses within the
      tag lifetime, converting early-LTP to late-LTP.

- Luboeinski & Tetzlaff (2021), Frontiers Comp Neurosci:
  Simplified STC with bistable consolidation variable z:
      dz/dt = z * (1 - z) * (z - 0.5)
  Fixed points at z=0 (no consolidation) and z=1 (full consolidation).
  z=0.5 is the unstable separatrix — tags + PRPs push z above 0.5,
  leading to stable consolidation at z=1. Without PRPs, z decays to 0.

Timescale adaptation
--------------------
Biological STC operates on a ~90-minute tag window with inter-event
intervals of ~100ms between synaptic activations. In Cortex, memory
storage events are separated by ~1 hour. We adapt the tag window to
48 hours, preserving the qualitative behavior: a strong event can
retroactively strengthen weak memories from the recent past, but not
arbitrarily old ones.

Biological ratio: 90 min window / 100 ms inter-event = 54,000 events.
Cortex ratio:     48 h window / 1 h inter-event = 48 events.

The Cortex ratio is much smaller because: (1) each "event" in Cortex
carries far more information than a single spike, (2) our entity-overlap
proxy for spatial proximity already provides strong selectivity that
biological proximity does not, and (3) 48h empirically covers the
typical working-session span where related memories cluster.

Spatial proximity proxy
-----------------------
The biological model requires synaptic tags to be on nearby dendritic
branches for PRP capture to occur. We lack neural topology, so we use
entity overlap (Szymkiewicz-Simpson coefficient) as a proxy: memories
sharing entities are treated as "spatially proximate."

Pure business logic — no I/O.
"""

from __future__ import annotations

from typing import Any

# ── Hand-tuned constants ─────────────────────────────────────────────────
# These are engineering parameters with no direct biological equivalent.
# Each is documented with its role in the STC analogy.

# Minimum importance of the new memory to trigger PRP synthesis.
# Maps to: "strong tetanization" threshold in Frey & Morris (1997).
# Hand-tuned: 0.7 chosen so only top-30% importance events produce PRPs.
_DEFAULT_TRIGGER_IMPORTANCE: float = 0.7

# Maximum importance of old memories eligible for tag capture.
# Memories above this threshold are already "late-LTP" and don't need
# retroactive promotion. Hand-tuned: 0.5 = median importance.
_DEFAULT_MAX_WEAK_IMPORTANCE: float = 0.5

# Minimum Szymkiewicz-Simpson overlap to consider memories "spatially
# proximate" (i.e., on the same dendritic branch). Hand-tuned: 0.3
# balances selectivity with recall — lower values cause too many
# false promotions, higher values miss legitimate associations.
_DEFAULT_MIN_OVERLAP: float = 0.3

# Additive importance boost for captured synapses (E-LTP -> L-LTP).
# Hand-tuned: 0.25 moves a typical weak memory (0.3) to moderate (0.55).
_DEFAULT_IMPORTANCE_BOOST: float = 0.25

# Multiplicative heat reheat factor for captured synapses.
# Hand-tuned: 1.5x re-raises heat to resist near-term decay.
_DEFAULT_HEAT_BOOST: float = 1.5

# Tag window in hours. See "Timescale adaptation" in module docstring.
# Biological value: ~90 minutes (Frey & Morris 1997).
# Adapted value: 48 hours (see docstring for ratio justification).
_DEFAULT_TAG_WINDOW_HOURS: float = 48.0

# Maximum captures per PRP-producing event.
# Hand-tuned: biological PRP diffusion is limited by distance; we cap
# at 5 to prevent a single strong event from promoting too many memories.
_DEFAULT_MAX_PROMOTIONS: int = 5

# Bistable consolidation threshold (Luboeinski & Tetzlaff 2021).
# z > BISTABLE_THRESHOLD converges to 1.0 (full consolidation).
# z < BISTABLE_THRESHOLD converges to 0.0 (tag decay, no capture).
# From the paper: the unstable fixed point is at z = 0.5.
_BISTABLE_THRESHOLD: float = 0.5


def bistable_consolidation(z: float, dt: float = 1.0) -> float:
    """Evaluate the Luboeinski bistable consolidation ODE.

    Implements dz/dt = z * (1 - z) * (z - 0.5) from Luboeinski &
    Tetzlaff (2021). Fixed points: z=0 (stable, no consolidation),
    z=0.5 (unstable separatrix), z=1 (stable, full consolidation).

    Parameters
    ----------
    z : Current consolidation state in [0, 1].
    dt : Time step for Euler integration. Default 1.0 (one discrete step).

    Returns
    -------
    Updated z, clamped to [0, 1].
    """
    dz = z * (1.0 - z) * (z - _BISTABLE_THRESHOLD)
    z_new = z + dz * dt
    return max(0.0, min(1.0, z_new))


def compute_initial_z(
    has_prp: bool,
    overlap: float,
) -> float:
    """Compute the initial consolidation variable z for a tagged synapse.

    In the Luboeinski model, z must exceed 0.5 to converge to full
    consolidation. PRPs from a strong event push z above the threshold
    proportionally to spatial proximity (entity overlap).

    Without PRPs (weak event only), z starts below threshold and will
    decay to 0 — the tag was set but no capture occurs.

    Parameters
    ----------
    has_prp : Whether PRPs are available (strong event occurred nearby).
    overlap : Entity overlap ratio [0, 1] — proxy for spatial proximity.
    """
    if not has_prp:
        # Tag set but no PRPs available — z below threshold, will decay.
        return overlap * 0.4  # max 0.4 < 0.5 threshold

    # PRPs available: z = 0.5 + overlap * 0.5, so z in [0.5, 1.0].
    # At overlap=0.3 (minimum), z = 0.65 — safely above threshold.
    return _BISTABLE_THRESHOLD + overlap * _BISTABLE_THRESHOLD


def _score_candidate(
    mem: dict[str, Any],
    new_memory_entities: set[str],
    max_weak_importance: float,
    tag_window_hours: float,
    min_overlap: float,
) -> tuple[float, dict[str, Any]] | None:
    """Score a single memory as a tagging candidate.

    A candidate must be:
    - Weak (importance <= max_weak_importance) — already-strong memories
      are already in late-LTP and don't need capture.
    - Recent (age <= tag_window_hours) — the synaptic tag has not expired.
    - Sharing entities with the triggering memory — proxy for dendritic
      proximity required for PRP diffusion.

    Returns (overlap, candidate_dict) or None if ineligible.
    """
    if mem.get("importance", 0) > max_weak_importance:
        return None
    if mem.get("age_hours", 999) > tag_window_hours:
        return None

    mem_entities = mem.get("entities", set())
    if not mem_entities:
        return None

    intersection = new_memory_entities & mem_entities
    if not intersection:
        return None

    # Szymkiewicz-Simpson overlap coefficient.
    # Not from the STC papers — an engineering choice for measuring
    # entity set similarity that handles asymmetric set sizes well.
    overlap = len(intersection) / min(len(new_memory_entities), len(mem_entities))
    if overlap < min_overlap:
        return None

    # Compute initial consolidation state via Luboeinski bistable model.
    # PRPs are available because this function is only called when the
    # triggering memory exceeds the PRP synthesis threshold.
    z_initial = compute_initial_z(has_prp=True, overlap=overlap)
    z_final = bistable_consolidation(z_initial)

    return (
        overlap,
        {
            "memory_id": mem["id"],
            "overlap": round(overlap, 4),
            "matched_entities": sorted(intersection),
            "consolidation_z": round(z_final, 4),
        },
    )


def find_tagging_candidates(
    new_memory_entities: set[str],
    new_memory_importance: float,
    existing_memories: list[dict[str, Any]],
    trigger_importance: float = _DEFAULT_TRIGGER_IMPORTANCE,
    max_weak_importance: float = _DEFAULT_MAX_WEAK_IMPORTANCE,
    min_overlap: float = _DEFAULT_MIN_OVERLAP,
    tag_window_hours: float = _DEFAULT_TAG_WINDOW_HOURS,
    max_promotions: int = _DEFAULT_MAX_PROMOTIONS,
) -> list[dict[str, Any]]:
    """Find weak memories eligible for synaptic tag capture.

    STC pipeline (Clopath et al. 2008):
      1. Check PRP trigger: new memory importance >= trigger_importance.
         Only strong events synthesize PRPs.
      2. Scan existing memories for those with active tags (recent, weak,
         sharing entities) — the Szymkiewicz-Simpson overlap coefficient
         measures "spatial proximity."
      3. Compute bistable consolidation z for each candidate
         (Luboeinski & Tetzlaff 2021).
      4. Rank by overlap (PRP diffusion favors proximate synapses),
         return top max_promotions.

    Returns
    -------
    List of dicts with 'memory_id', 'overlap', 'matched_entities',
    and 'consolidation_z'.
    """
    # Gate: only strong events produce PRPs (Frey & Morris 1997).
    if new_memory_importance < trigger_importance or not new_memory_entities:
        return []

    candidates: list[tuple[float, dict[str, Any]]] = []
    for mem in existing_memories:
        result = _score_candidate(
            mem,
            new_memory_entities,
            max_weak_importance,
            tag_window_hours,
            min_overlap,
        )
        if result is not None:
            candidates.append(result)

    # Rank by overlap — closer synapses capture PRPs first.
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [c[1] for c in candidates[:max_promotions]]


def compute_tag_boosts(
    overlap: float,
    current_importance: float,
    current_heat: float,
    importance_boost: float = _DEFAULT_IMPORTANCE_BOOST,
    heat_boost: float = _DEFAULT_HEAT_BOOST,
) -> dict[str, float]:
    """Compute boost values for a captured synapse (E-LTP -> L-LTP).

    The boost magnitude scales with entity overlap — higher overlap means
    closer spatial proximity, so more PRP diffusion reaches the tagged
    synapse (Clopath et al. 2008).

    The bistable consolidation variable z (Luboeinski & Tetzlaff 2021)
    further modulates the boost: z converges toward 1.0 when PRPs are
    present and overlap is sufficient, amplifying the promotion.

    Parameters
    ----------
    overlap : Entity overlap ratio [0, 1] — proxy for PRP diffusion reach.
    current_importance : Current importance of the weak (E-LTP) memory.
    current_heat : Current heat of the weak memory.
    importance_boost : Base additive importance boost. Hand-tuned: 0.25.
    heat_boost : Base multiplicative heat boost. Hand-tuned: 1.5.

    Returns
    -------
    Dict with 'new_importance', 'new_heat', 'importance_delta',
    'heat_delta', and 'consolidation_z'.
    """
    # Bistable consolidation from Luboeinski: z above 0.5 converges to 1.
    z = compute_initial_z(has_prp=True, overlap=overlap)
    z = bistable_consolidation(z)

    # Scale boosts by both overlap and consolidation state.
    # When z -> 1.0 (full consolidation), the full boost is applied.
    scaled_importance = importance_boost * overlap * z
    new_importance = min(1.0, current_importance + scaled_importance)

    scaled_heat = 1.0 + (heat_boost - 1.0) * overlap * z
    new_heat = min(1.0, current_heat * scaled_heat)

    return {
        "new_importance": round(new_importance, 4),
        "new_heat": round(new_heat, 4),
        "importance_delta": round(new_importance - current_importance, 4),
        "heat_delta": round(new_heat - current_heat, 4),
        "consolidation_z": round(z, 4),
    }


def _boost_candidate(
    candidate: dict[str, Any],
    existing_memories: list[dict[str, Any]],
    importance_boost: float,
    heat_boost: float,
) -> dict[str, Any] | None:
    """Look up the candidate memory and compute its capture boost."""
    mem = next(
        (m for m in existing_memories if m["id"] == candidate["memory_id"]),
        None,
    )
    if not mem:
        return None
    boosts = compute_tag_boosts(
        overlap=candidate["overlap"],
        current_importance=mem.get("importance", 0.5),
        current_heat=mem.get("heat", 0.1),
        importance_boost=importance_boost,
        heat_boost=heat_boost,
    )
    return {**candidate, **boosts}


def apply_synaptic_tags(
    new_memory_entities: set[str],
    new_memory_importance: float,
    existing_memories: list[dict[str, Any]],
    trigger_importance: float = _DEFAULT_TRIGGER_IMPORTANCE,
    max_weak_importance: float = _DEFAULT_MAX_WEAK_IMPORTANCE,
    min_overlap: float = _DEFAULT_MIN_OVERLAP,
    tag_window_hours: float = _DEFAULT_TAG_WINDOW_HOURS,
    max_promotions: int = _DEFAULT_MAX_PROMOTIONS,
    importance_boost: float = _DEFAULT_IMPORTANCE_BOOST,
    heat_boost: float = _DEFAULT_HEAT_BOOST,
) -> list[dict[str, Any]]:
    """Full STC pipeline: find tagged synapses and compute capture boosts.

    Implements the complete Synaptic Tagging & Capture sequence:
    1. Strong event (importance >= threshold) triggers PRP synthesis.
    2. Scan for weak memories with active tags (recent + entity overlap).
    3. Compute bistable consolidation z for each (Luboeinski model).
    4. Apply PRP-modulated boosts to importance and heat.
    """
    candidates = find_tagging_candidates(
        new_memory_entities=new_memory_entities,
        new_memory_importance=new_memory_importance,
        existing_memories=existing_memories,
        trigger_importance=trigger_importance,
        max_weak_importance=max_weak_importance,
        min_overlap=min_overlap,
        tag_window_hours=tag_window_hours,
        max_promotions=max_promotions,
    )

    results = []
    for candidate in candidates:
        boosted = _boost_candidate(
            candidate,
            existing_memories,
            importance_boost,
            heat_boost,
        )
        if boosted is not None:
            results.append(boosted)

    return results
