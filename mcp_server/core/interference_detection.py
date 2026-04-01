"""Interference detection — proactive and retroactive interference helpers.

Extracted from interference.py to respect the 300-line/40-line limits.

Computational model:
    Norman KA, Newman EL, Detre GJ (2007) A neural network model of
    retrieval-induced forgetting. Psychological Review 114:887-953.

    Norman et al. model interference as competition between memory
    representations in a leaky competing accumulator (LCA). Proactive
    interference arises when strong existing representations (high
    activation from prior learning) compete with new encoding. Retroactive
    interference arises when new high-activation representations disrupt
    access to older, weaker ones.

    Our detection functions identify these competitive dynamics using
    cosine similarity as a proxy for representational overlap (which
    determines the strength of lateral inhibition in the LCA) and
    consolidation stage as a proxy for connection strength (which
    determines interference resistance in the neural model).

Additional references:
    Anderson MC, Neely JH (1996) Interference and inhibition in memory
    retrieval. — Behavioral framework for retrieval-induced forgetting.
    Provides the proactive/retroactive distinction used here.

    Wixted JT (2004) The psychology and neuroscience of forgetting.
    — Review article; no equations. Cited for conceptual context on
    the interference vs. decay debate.

Pure business logic — no I/O.
"""

from __future__ import annotations

from mcp_server.shared.linear_algebra import cosine_similarity
from mcp_server.shared.similarity import jaccard_similarity

# ── Configuration ─────────────────────────────────────────────────────────
# All constants are hand-tuned for this system's operating regime.
# No direct mapping to Norman et al. 2007's neural model parameters.

# Cosine similarity above which two memories are considered interfering.
# Hand-tuned; see interference.py for rationale.
_INTERFERENCE_THRESHOLD = 0.7

# Discount applied when memories are in different directory contexts.
# Models context-dependent interference: memories encoded in different
# contexts interfere less (consistent with Anderson & Neely 1996's
# context-based accounts). Hand-tuned.
_CONTEXT_DISCOUNT = 0.3

# Score above which interference is considered critical, triggering
# aggressive resolution (pattern separation or memory protection).
# Hand-tuned.
_CRITICAL_INTERFERENCE = 0.85


# ── Resolution Hints ─────────────────────────────────────────────────────


def _suggest_pi_resolution(score: float, similarity: float, stage: str) -> str:
    """Suggest resolution strategy for proactive interference.

    Maps interference severity to resolution strategies inspired by
    Norman et al. 2007: high interference triggers pattern separation
    (orthogonalization); near-duplicate triggers merge; consolidated
    blockers use context binding to differentiate.
    """
    if score >= _CRITICAL_INTERFERENCE:
        return "pattern_separation"
    if similarity > 0.9:
        return "merge_or_update"
    if stage == "consolidated":
        return "context_binding"
    return "normal_encoding"


def _suggest_ri_resolution(score: float, stage: str, heat: float) -> str:
    """Suggest resolution strategy for retroactive interference.

    In Norman et al. 2007, weakly encoded items are most vulnerable
    to retroactive interference. We map consolidation stage to
    vulnerability: labile/early_ltp items need accelerated
    consolidation; cold consolidated items can accept overwrite.
    """
    if score >= _CRITICAL_INTERFERENCE:
        return "protect_old_memory"
    if stage in ("labile", "early_ltp"):
        return "accelerate_consolidation"
    if heat < 0.2:
        return "accept_overwrite"
    return "orthogonalize_at_sleep"


# ── Proactive Interference ───────────────────────────────────────────────


def _compute_pi_score(
    sim: float,
    entity_overlap: float,
    heat_factor: float,
    stage: str,
    context_match: float,
) -> float:
    """Compute proactive interference score from component signals.

    Weighted combination of similarity (representational overlap),
    entity overlap (semantic relatedness), heat (recent activation
    strength), and consolidation stage (connection strength). Weights
    are hand-tuned; the relative ordering (similarity > entities >
    heat > stage) reflects Norman et al. 2007's emphasis on
    representational overlap as the primary driver of competition.

    Stage factors approximate interference resistance from consolidation:
        consolidated: 1.2 — strong prior representations compete more
        late_ltp: 1.0 — baseline
        early_ltp: 0.8 — partially consolidated, moderate competition
        labile: 0.5 — weakly encoded, minimal proactive effect
    All stage factors are hand-tuned.
    """
    stage_factor = {
        "consolidated": 1.2,
        "late_ltp": 1.0,
        "early_ltp": 0.8,
        "labile": 0.5,
    }.get(stage, 0.7)

    return (
        sim * 0.4 + entity_overlap * 0.25 + heat_factor * 0.2 + stage_factor * 0.15
    ) * context_match


def _compute_pi_context_match(mem: dict) -> float:
    """Context discount: different directories reduce interference.

    Models context-dependent interference (Anderson & Neely 1996):
    memories encoded in different working contexts interfere less.
    Discount factor is hand-tuned.
    """
    if mem.get("directory_context") and mem["directory_context"] != mem.get(
        "new_directory", ""
    ):
        return 1.0 - _CONTEXT_DISCOUNT
    return 1.0


def _build_pi_result(
    mem: dict,
    sim: float,
    entity_overlap: float,
    score: float,
    stage: str,
) -> dict:
    """Build a proactive interference result dict."""
    return {
        "memory_id": mem.get("id"),
        "similarity": round(sim, 4),
        "entity_overlap": round(entity_overlap, 4),
        "interference_score": round(score, 4),
        "interference_type": "proactive",
        "resolution_hint": _suggest_pi_resolution(score, sim, stage),
    }


def _evaluate_pi_candidate(
    mem: dict,
    new_embedding: list[float],
    new_entity_set: set[str],
    threshold: float,
) -> dict | None:
    """Evaluate one existing memory for proactive interference."""
    emb = mem.get("embedding")
    if not emb or len(emb) != len(new_embedding):
        return None

    sim = cosine_similarity(new_embedding, emb)
    if sim < threshold:
        return None

    mem_entities = set(mem.get("entities", []))
    entity_overlap = (
        jaccard_similarity(new_entity_set, mem_entities)
        if (new_entity_set or mem_entities)
        else 0.0
    )

    stage = mem.get("consolidation_stage", "labile")
    score = _compute_pi_score(
        sim, entity_overlap, mem.get("heat", 0.5), stage, _compute_pi_context_match(mem)
    )
    if score < threshold * 0.7:
        return None

    return _build_pi_result(mem, sim, entity_overlap, score, stage)


def detect_proactive_interference(
    new_memory_embedding: list[float],
    new_memory_entities: list[str],
    existing_memories: list[dict],
    *,
    threshold: float = _INTERFERENCE_THRESHOLD,
) -> list[dict]:
    """Detect old memories that may interfere with encoding a new memory.

    Proactive interference (Anderson & Neely 1996) occurs when existing
    high-activation memories compete with the new memory for the same
    representational space. In Norman et al. 2007's LCA model, this
    corresponds to strong prior patterns suppressing the new pattern
    through lateral inhibition during the high-g phase.

    Args:
        new_memory_embedding: Embedding of the incoming memory.
        new_memory_entities: Entities in the incoming memory.
        existing_memories: List of dicts with 'embedding', 'entities', 'heat',
            'id', 'directory_context', 'consolidation_stage'.
        threshold: Similarity threshold for interference (hand-tuned).

    Returns:
        List of interference descriptors, sorted by severity.
    """
    new_entity_set = set(new_memory_entities)
    interferences = []

    for mem in existing_memories:
        result = _evaluate_pi_candidate(
            mem,
            new_memory_embedding,
            new_entity_set,
            threshold,
        )
        if result is not None:
            interferences.append(result)

    interferences.sort(key=lambda x: x["interference_score"], reverse=True)
    return interferences


# ── Retroactive Interference ─────────────────────────────────────────────


def _compute_vulnerability(
    old_stage: str,
    sim: float,
    old_heat: float,
    old_importance: float,
) -> float:
    """Compute how vulnerable an old memory is to overwriting.

    In Norman et al. 2007, weakly encoded patterns (low connection
    strength) are most susceptible to interference from new, strongly
    activated patterns. We model this through consolidation stage
    (resistance), heat (activation recency), and importance (encoding
    strength). The formula: (1 - resistance) * (1 - heat_boost) *
    (1 - importance_boost). All scaling factors are hand-tuned.
    """
    from mcp_server.core.cascade_stages import compute_interference_resistance

    resistance = compute_interference_resistance(old_stage, sim)
    return (1.0 - resistance) * (1.0 - old_heat * 0.5) * (1.0 - old_importance * 0.3)


def _evaluate_ri_candidate(
    mem: dict,
    new_embedding: list[float],
    new_importance: float,
    threshold: float,
) -> dict | None:
    """Evaluate one existing memory for retroactive interference risk."""
    emb = mem.get("embedding")
    if not emb or len(emb) != len(new_embedding):
        return None

    sim = cosine_similarity(new_embedding, emb)
    if sim < threshold:
        return None

    old_heat = mem.get("heat", 0.5)
    old_importance = mem.get("importance", 0.5)
    old_stage = mem.get("consolidation_stage", "labile")

    vulnerability = _compute_vulnerability(old_stage, sim, old_heat, old_importance)
    overwrite_pressure = new_importance * sim
    risk_score = vulnerability * overwrite_pressure

    # Hand-tuned threshold: below 0.2 risk is negligible.
    if risk_score <= 0.2:
        return None

    return {
        "memory_id": mem.get("id"),
        "similarity": round(sim, 4),
        "vulnerability": round(vulnerability, 4),
        "overwrite_pressure": round(overwrite_pressure, 4),
        "risk_score": round(risk_score, 4),
        "interference_type": "retroactive",
        "resolution_hint": _suggest_ri_resolution(risk_score, old_stage, old_heat),
    }


def detect_retroactive_interference(
    new_memory_embedding: list[float],
    new_memory_importance: float,
    existing_memories: list[dict],
    *,
    threshold: float = _INTERFERENCE_THRESHOLD,
) -> list[dict]:
    """Detect old memories at risk of being overwritten by a new memory.

    Retroactive interference (Anderson & Neely 1996) occurs when a new
    high-importance memory threatens to corrupt similar existing memories.
    In Norman et al. 2007's model, this corresponds to new strongly
    activated patterns suppressing weaker existing patterns through the
    LCA competition dynamics.

    Args:
        new_memory_embedding: Embedding of the incoming memory.
        new_memory_importance: Importance of the incoming memory.
        existing_memories: List of memory dicts.
        threshold: Similarity threshold for interference (hand-tuned).

    Returns:
        List of at-risk memories with interference descriptors.
    """
    at_risk = []

    for mem in existing_memories:
        result = _evaluate_ri_candidate(
            mem,
            new_memory_embedding,
            new_memory_importance,
            threshold,
        )
        if result is not None:
            at_risk.append(result)

    at_risk.sort(key=lambda x: x["risk_score"], reverse=True)
    return at_risk
