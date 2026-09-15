"""Post-WRRF retrieval and reranking stages.

source: ADR-0235
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.ablation import Mechanism, is_mechanism_disabled
from mcp_server.core.environment import read_environment_float
from mcp_server.core.capture_origin import ORIGIN_UNKNOWN, is_trusted_at_read
from mcp_server.observability import silent_failure
from mcp_server.core import dual_process_retrieval as dpr, hopfield, conflict_monitor
from mcp_server.core.hopfield import cosine_similarity
from mcp_server.core.hdc_encoder import compute_hdc_scores
from mcp_server.core.query_decomposition import extract_query_entities
from mcp_server.shared.text import extract_keywords
from mcp_server.shared.similarity import jaccard_similarity
from mcp_server.shared.vader import vader_compound
from mcp_server.core.value_learning import retrieval_priority
from mcp_server.core.goal_maintenance import (
    goal_recall_multiplier,
    goal_vector_is_active,
)
from mcp_server.core.attentional_control import allocate_attention
from mcp_server.core.reconsolidation import compute_reconsolidation_action

logger = logging.getLogger(__name__)

# source: ADR-0235


_RRF_K: int = 60

# source: ADR-0235


_SHORT_TOKEN_MAX_LEN: int = 2

# source: ADR-0235


_MIN_RERANK_CANDIDATES: int = 2

# source: ADR-0235

_ENTITY_FALLBACK_TOKEN_MIN_LEN: int = 4


# Lazily-resolved, process-lifetime-cached tuning knobs (env-var overrides).
# Deferred to first *use* rather than read at module-def time (the
# pre-#560 behavior): core/environment.py's reader is wired by the
# composition root (__main__.py/conftest.py) possibly after this module is
# first imported transitively, so reading at def time could silently miss
# a real operator override. Nothing changes these vars after process
# startup, so "resolved on first call, cached forever" is observably
# identical to "resolved at import" for every caller. source: issue #560
_TUNING_CACHE: dict[str, float] = {}


def _tuning_float(name: str, default: float) -> float:
    """Resolve+cache one env-var tuning knob for the process lifetime.

    source: issue #560"""
    if name not in _TUNING_CACHE:
        _TUNING_CACHE[name] = read_environment_float(name, default)
    return _TUNING_CACHE[name]


# source: ADR-0235


_EMOTIONAL_QUERY_VALENCE_FLOOR: float = 0.10


# ── Helpers ─────────────────────────────────────────────────────────────


def _rrf_blend(
    candidates: list[dict[str, Any]],
    mech_ranks: dict[Any, int],
    beta: float,
    k: int = _RRF_K,
) -> list[dict[str, Any]]:
    """Blend the existing candidate order with a mechanism's rank vector.

    ``mech_ranks`` maps memory_id → rank within the mechanism's output
    (0 = best). Candidates absent from mech_ranks keep their relevance
    rank only.

    source: ADR-0235"""
    if not candidates or beta <= 0.0:
        return candidates

    n = len(candidates)
    fallback_rank = n  # "not in mech ranking" → demote, don't disqualify

    scored: list[tuple[float, dict[str, Any]]] = []
    for rel_rank, c in enumerate(candidates):
        mid = c["memory_id"]
        m_rank = mech_ranks.get(mid, fallback_rank)
        new_score = (1.0 - beta) / (k + rel_rank) + beta / (k + m_rank)
        c_out = dict(c)
        c_out["score"] = float(new_score)
        scored.append((new_score, c_out))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [c for _, c in scored]


# source: ADR-0235


def familiarity_triage(
    candidates: list[dict[str, Any]],
    q_emb: bytes | None,
    store: Any,
    *,
    allow_shortcut: bool = False,
):
    """Early a-contextual familiarity triage over the WRRF candidates (C2).

    Reads each candidate's embedding in ONE bulk PG round trip (the same
    ``get_embeddings_for_memories`` path the Hopfield stage uses), computes the
    query↔candidate cosine similarity for each, and hands the similarity vector
    to ``dual_process_retrieval.triage``. The result carries:

      source: ADR-0235"""

    # Ablation / degenerate guards: identity triage (full recollection runs).
    if is_mechanism_disabled(Mechanism.DUAL_PROCESS) or not candidates or q_emb is None:
        return dpr.TriageResult(
            candidates=candidates,
            signal=dpr.assess_familiarity([], method=dpr.METHOD_EMPTY),
            recollection_needed=True,
            shortcut=False,
        )

    ids = [c["memory_id"] for c in candidates]
    emb_by_id: dict[Any, bytes] = {}
    if hasattr(store, "get_embeddings_for_memories"):
        emb_by_id = store.get_embeddings_for_memories(ids)
    elif hasattr(store, "get_memory"):
        for mid in ids:
            mem = store.get_memory(mid)
            if mem and mem.get("embedding"):
                emb_by_id[mid] = mem["embedding"]

    # No embeddings available (test stub without a store, un-embedded corpus):
    # identity triage — we do NOT fabricate a familiarity signal, and the
    # recollection chain runs in full.
    if not emb_by_id:
        return dpr.TriageResult(
            candidates=candidates,
            signal=dpr.assess_familiarity([], method=dpr.METHOD_EMPTY),
            recollection_needed=True,
            shortcut=False,
        )

    sims: list[float] = []
    for c in candidates:
        emb = emb_by_id.get(c["memory_id"])
        if emb is None:
            sims.append(0.0)  # missing embedding contributes no familiarity
            continue
        try:
            sims.append(cosine_similarity(q_emb, emb))
        except Exception:  # noqa: BLE001 — source: ADR-0235
            sims.append(0.0)

    return dpr.triage(
        candidates,
        sims,
        allow_shortcut=allow_shortcut,
        method=dpr.METHOD_VECTOR,
    )


# source: ADR-0235


def hopfield_complete(
    candidates: list[dict[str, Any]],
    q_emb: bytes | None,
    store: Any,
    embedding_dim: int,
    *,
    hopfield_beta: float = 8.0,
    blend_beta: float | None = None,
) -> list[dict[str, Any]]:
    """Reorder candidates by Hopfield attention rank, RRF-blended with WRRF.

    The Hopfield pattern matrix is built from the candidates' own embeddings
    (fetched from the store in **one bulk PG call**, not N per-candidate
    round-trips). Hopfield attention then ranks them by
    ``softmax(beta * X · query)``; we blend that rank with the WRRF rank.

    source: ADR-0235"""
    if blend_beta is None:
        blend_beta = _tuning_float("CORTEX_HOPFIELD_BETA", 0.30)
    if is_mechanism_disabled(Mechanism.HOPFIELD):
        return candidates
    if not candidates or q_emb is None:
        return candidates

    # Single bulk round trip when the store supports it; else fall back.
    ids = [c["memory_id"] for c in candidates]
    pairs: list[tuple[int, bytes]] = []
    if hasattr(store, "get_embeddings_for_memories"):
        emb_by_id = store.get_embeddings_for_memories(ids)
        for mid in ids:
            emb = emb_by_id.get(mid)
            if emb:
                pairs.append((mid, emb))
    elif hasattr(store, "get_memory"):
        for mid in ids:
            mem = store.get_memory(mid)
            if mem and mem.get("embedding"):
                pairs.append((mid, mem["embedding"]))

    if not pairs:
        return candidates

    mat, ids = hopfield.build_pattern_matrix(pairs, embedding_dim)
    if mat.size == 0:
        return candidates

    hop = hopfield.retrieve(q_emb, mat, ids, beta=hopfield_beta, top_k=len(ids))
    if not hop:
        return candidates

    mech_ranks = {mid: rank for rank, (mid, _) in enumerate(hop)}
    return _rrf_blend(candidates, mech_ranks, blend_beta)


# source: ADR-0235


def hdc_rerank(
    candidates: list[dict[str, Any]],
    query: str,
    *,
    blend_beta: float | None = None,
) -> list[dict[str, Any]]:
    """Reorder candidates by HDC similarity, RRF-blended with WRRF.

    Each candidate's content is encoded as a bipolar hypervector
    (bundle of word atoms + bigram binds); HDC similarity = dot/dim.

    source: ADR-0235"""
    if blend_beta is None:
        blend_beta = _tuning_float("CORTEX_HDC_BETA", 0.20)
    if is_mechanism_disabled(Mechanism.HDC):
        return candidates
    if not candidates:
        return candidates

    pairs = [(c["memory_id"], c.get("content", "") or "") for c in candidates]
    hdc = compute_hdc_scores(query, pairs, threshold=-1.0)  # keep all ranks
    if not hdc:
        return candidates

    mech_ranks = {mid: rank for rank, (mid, _) in enumerate(hdc)}
    return _rrf_blend(candidates, mech_ranks, blend_beta)


# source: ADR-0235


# source: ADR-0235


_sa_failed: bool = False
_sa_last_error: str | None = None


def spreading_activation_status() -> dict[str, str | None]:
    """Report the SA channel's last-known failure state without retrying.

    Precondition: none. Postcondition: ``failed`` is True iff a prior
    SA call (either mode) caught an exception from
    ``store.spread_activation_memories``; ``error`` carries that
    exception's text, else None. Never triggers a call itself.
    """
    return {"failed": str(_sa_failed), "error": _sa_last_error}


def _sa_query_terms(query: str) -> list[str]:
    """Extract query terms for entity-name seed resolution (shared by
    both SA modes)."""

    return list(
        set(
            extract_query_entities(query)
            + [w for w in query.split() if len(w) > _SHORT_TOKEN_MAX_LEN]
        )
    )


def _run_spread_activation(
    query: str,
    store: Any,
    *,
    domain: str | None,
    include_globals: bool,
    cross_domain: bool,
    decay: float,
    threshold: float,
    max_depth: int,
    max_results: int,
    min_heat: float,
) -> list[tuple[int, float]]:
    """Ablation gate + terms + store call + non-silent-failure logging.

    source: ADR-0235"""
    if is_mechanism_disabled(Mechanism.SPREADING_ACTIVATION):
        return []
    if not hasattr(store, "spread_activation_memories"):
        return []
    terms = _sa_query_terms(query)
    if not terms:
        return []

    global _sa_failed, _sa_last_error
    try:
        return store.spread_activation_memories(
            query_terms=terms,
            decay=decay,
            threshold=threshold,
            max_depth=max_depth,
            max_results=max_results,
            min_heat=min_heat,
            domain=None if cross_domain else domain,
            include_globals=include_globals,
        )
    except Exception as exc:  # noqa: BLE001 — source: ADR-0235
        # source: ADR-0235

        if not _sa_failed:
            logger.warning(
                "spread_activation_memories failed (domain=%s, "
                "cross_domain=%s): %s -- SA channel DISABLED for this and "
                "subsequent calls in this process; recall falls back to "
                "the WRRF-ranked candidates unchanged. Further failures "
                "are suppressed from the log but remain visible via "
                "spreading_activation_status().",
                domain,
                cross_domain,
                exc,
            )
        _sa_failed = True
        _sa_last_error = str(exc)
        return []


# source: ADR-0235


def _sa_candidate_from_memory(mid: int, mem: dict[str, Any]) -> dict[str, Any]:
    """Build a WRRF-contract-shaped candidate dict from a get_memory() row.

    source: ADR-0235"""
    return {
        "memory_id": mid,
        "content": mem.get("content", ""),
        "score": 0.0,  # caller sets the real score (RRF blend or tail default)
        "heat": mem.get("heat", 0.0),
        "domain": mem.get("domain", ""),
        "created_at": mem.get("created_at", ""),
        "store_type": mem.get("store_type", "episodic"),
        "tags": mem.get("tags", []),
        "importance": mem.get("importance", 0.5),
        "surprise_score": mem.get("surprise_score", 0.0),
        "emotional_valence": mem.get("emotional_valence", 0.0),
        "source": mem.get("source", ""),
        "value": mem.get("value", 0.5),
        "source_attribution": mem.get("source_attribution"),
        # source: ADR-0235
        "capture_origin": mem.get("capture_origin", ORIGIN_UNKNOWN),
        "_sa_injected": True,
    }


def spreading_activation_expand(
    candidates: list[dict[str, Any]],
    query: str,
    store: Any,
    *,
    domain: str | None = None,
    include_globals: bool = True,
    cross_domain: bool = False,
    decay: float = 0.65,
    threshold: float = 0.1,
    max_depth: int = 3,
    max_results: int = 50,
    min_heat: float = 0.05,
    blend_beta: float | None = None,
) -> list[dict[str, Any]]:
    """AUGMENT mode: expand the candidate pool with SA-reachable memories,
    then RRF blend (can reorder and outrank existing candidates).

    source: ADR-0235

    Disabled when ``CORTEX_ABLATE_SPREADING_ACTIVATION=1`` — returns
    input unchanged.
    """
    if blend_beta is None:
        blend_beta = _tuning_float("CORTEX_SA_BETA", 0.25)
    if not candidates:
        return candidates
    sa = _run_spread_activation(
        query,
        store,
        domain=domain,
        include_globals=include_globals,
        cross_domain=cross_domain,
        decay=decay,
        threshold=threshold,
        max_depth=max_depth,
        max_results=max_results,
        min_heat=min_heat,
    )
    if not sa:
        return candidates

    existing_ids = {c["memory_id"] for c in candidates}
    expanded = list(candidates)

    for mid, _act in sa:
        if mid in existing_ids:
            continue
        if not hasattr(store, "get_memory"):
            continue
        mem = store.get_memory(mid)
        if not mem:
            continue
        expanded.append(_sa_candidate_from_memory(mid, mem))
        existing_ids.add(mid)

    mech_ranks = {mid: rank for rank, (mid, _act) in enumerate(sa)}
    return _rrf_blend(expanded, mech_ranks, blend_beta)


def spreading_activation_tail_fill(
    candidates: list[dict[str, Any]],
    query: str,
    store: Any,
    top_k: int,
    *,
    domain: str | None = None,
    include_globals: bool = True,
    cross_domain: bool = False,
    decay: float = 0.65,
    threshold: float = 0.1,
    max_depth: int = 3,
    max_results: int = 50,
    min_heat: float = 0.05,
) -> list[dict[str, Any]]:
    """TAIL mode: append SA-reachable memories ONLY to fill a short list up to
    ``top_k``.

    source: ADR-0235

    Precondition: candidates is the final post-rerank list, after all
    reranking stages.
    Postcondition: filled[:len(candidates)] equals candidates with identical
    dictionaries and order; len(filled) <= top_k. Appended items obey the
    same WRRF field contract as spreading_activation_expand injections.
    source: ADR-0235

    Disabled when ``CORTEX_ABLATE_SPREADING_ACTIVATION=1`` — returns
    input unchanged (via ``_run_spread_activation``'s ablation gate,
    reached only once the length check has already passed).
    """
    if len(candidates) >= top_k:
        return candidates
    if not hasattr(store, "get_memory"):
        return candidates

    needed = top_k - len(candidates)
    sa = _run_spread_activation(
        query,
        store,
        domain=domain,
        include_globals=include_globals,
        cross_domain=cross_domain,
        decay=decay,
        threshold=threshold,
        max_depth=max_depth,
        max_results=max_results,
        min_heat=min_heat,
    )
    if not sa:
        return candidates

    existing_ids = {c["memory_id"] for c in candidates}
    filled = list(candidates)
    added = 0
    for mid, _act in sa:
        if added >= needed:
            break
        if mid in existing_ids:
            continue
        mem = store.get_memory(mid)
        if not mem:
            continue
        filled.append(_sa_candidate_from_memory(mid, mem))
        existing_ids.add(mid)
        added += 1

    return filled


# source: ADR-0235


def _candidate_entities(c: dict[str, Any]) -> set[str]:
    """Extract a coarse entity-token set from a candidate's content."""
    content = (c.get("content") or "").lower()
    # Token-level proxy for entity overlap — same shape used by
    # dendritic_clusters.compute_branch_affinity (Jaccard over sets).
    return {
        t.strip(".,!?;:()[]{}\"'`")
        for t in content.split()
        if len(t) > _SHORT_TOKEN_MAX_LEN
    }


def _candidate_tags(c: dict[str, Any]) -> set[str]:
    """Normalize a candidate's tag set for Jaccard."""
    tags = c.get("tags") or []
    if isinstance(tags, str):
        return {tags}
    return {str(t) for t in tags}


def _resolve_query_entity_ids(query: str, store: Any) -> set[int]:
    """Resolve query entities to entity_ids.

    source: ADR-0235

    Constant cost per recall (typical query: ≤30 candidate tokens
    after stopword filter; each is one indexed lookup against the
    ``entities`` table's name index — sub-millisecond). Returns the
    empty set if nothing resolves; callers fall back to the
    token-Jaccard proxy.
    """

    if not hasattr(store, "get_entity_by_name"):
        return set()
    ids: set[int] = set()
    seen_names: set[str] = set()

    # Stage 1: high-precision extractor (CamelCase / paths / backticks).
    for name in extract_query_entities(query):
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        row = store.get_entity_by_name(name)
        if row and row.get("id") is not None:
            ids.add(int(row["id"]))

    # source: ADR-0235

    try:
        for token in extract_keywords(query):
            if len(token) < _ENTITY_FALLBACK_TOKEN_MIN_LEN or token in seen_names:
                continue
            seen_names.add(token)
            row = store.get_entity_by_name(token)
            if row and row.get("id") is not None:
                ids.add(int(row["id"]))
    except Exception as exc:  # noqa: BLE001
        # Fallback path is non-load-bearing; if the keyword extractor
        # ever fails on a malformed query we still have the stage-1 ids.
        silent_failure.note("recall_pipeline.keyword_entity_fallback", exc)

    return ids


def dendritic_modulate(
    candidates: list[dict[str, Any]],
    query: str,
    store: Any = None,
    *,
    delta: float | None = None,
) -> list[dict[str, Any]]:
    """Apply branch-affinity multiplicative modulation to candidate scores.

    source: ADR-0235"""
    if delta is None:
        delta = _tuning_float("CORTEX_DENDRITIC_DELTA", 0.10)
    if is_mechanism_disabled(Mechanism.DENDRITIC_CLUSTERS):
        return candidates
    if not candidates or delta <= 0.0:
        return candidates

    # Try the real entity-graph path first. q_eids is non-empty only
    # when both the store supports bulk-by-id AND the query resolves.
    q_eids: set[int] = set()
    ent_id_by_mem: dict[int, set[int]] = {}
    if store is not None and hasattr(store, "get_entity_ids_for_memories"):
        q_eids = _resolve_query_entity_ids(query, store)
        if q_eids:
            ids = [c["memory_id"] for c in candidates]
            ent_id_by_mem = store.get_entity_ids_for_memories(ids)

    # Token-proxy query set, used both as primary signal in the fallback
    # path and as the tag-Jaccard signal in the entity-graph path.
    q_tokens = {
        t.strip(".,!?;:()[]{}\"'`").lower()
        for t in query.split()
        if len(t) > _SHORT_TOKEN_MAX_LEN
    }
    if not q_tokens and not q_eids:
        return candidates

    modulated: list[dict[str, Any]] = []
    for c in candidates:
        if q_eids:
            c_eids = ent_id_by_mem.get(c["memory_id"], set())
            ent_sim = jaccard_similarity(q_eids, c_eids) if c_eids else 0.0
        else:
            c_entities = _candidate_entities(c)
            ent_sim = jaccard_similarity(q_tokens, c_entities) if c_entities else 0.0
        c_tags = _candidate_tags(c)
        tag_sim = jaccard_similarity(q_tokens, c_tags) if c_tags and q_tokens else 0.0
        affinity = 0.7 * ent_sim + 0.3 * tag_sim
        factor = 1.0 + delta * (2.0 * affinity - 1.0)
        c_out = dict(c)
        c_out["score"] = float(c.get("score", 0.0)) * factor
        modulated.append(c_out)

    modulated.sort(key=lambda c: c.get("score", 0.0), reverse=True)
    return modulated


# source: ADR-0235


def emotional_retrieval_rerank(
    candidates: list[dict[str, Any]],
    query: str,
    *,
    blend_beta: float | None = None,
    valence_floor: float = _EMOTIONAL_QUERY_VALENCE_FLOOR,
) -> list[dict[str, Any]]:
    """Rerank by query-valence ↔ candidate-valence congruence.

    source: ADR-0235

    Disabled when ``CORTEX_ABLATE_EMOTIONAL_RETRIEVAL=1`` — returns input
    unchanged. Distinct from MOOD_CONGRUENT_RERANK: this stage uses the
    *query's* valence (per-recall), not a session-level user mood state.

    source: ADR-0235"""
    if blend_beta is None:
        blend_beta = _tuning_float("CORTEX_EMOTIONAL_RETRIEVAL_BETA", 0.20)
    if is_mechanism_disabled(Mechanism.EMOTIONAL_RETRIEVAL):
        return candidates
    if not candidates:
        return candidates

    q_valence = vader_compound(query)
    if abs(q_valence) < valence_floor:
        # Neutral query — no useful congruence signal to inject.
        return candidates

    def _distance(c: dict[str, Any]) -> float:
        c_v = c.get("emotional_valence", 0.0) or 0.0
        return abs(float(c_v) - q_valence)

    by_match = sorted(enumerate(candidates), key=lambda x: _distance(x[1]))
    mech_ranks = {
        candidates[i]["memory_id"]: rank for rank, (i, _) in enumerate(by_match)
    }
    return _rrf_blend(candidates, mech_ranks, blend_beta)


# source: ADR-0235


def value_priority_rerank(
    candidates: list[dict[str, Any]],
    *,
    weight: float = 0.15,
) -> list[dict[str, Any]]:
    """Nudge each candidate's score by its learned RL value (B2).

    A memory's ``value`` (default 0.5 = neutral prior) scales its score by
    ``1 + weight·(value − 0.5)`` and the list is re-sorted. A memory with no
    learned value, or an un-migrated store where the column is absent, keeps the
    neutral prior and is unaffected — the stage is a no-op on a store that has
    never accrued value.

    Disabled when ``CORTEX_ABLATE_VALUE_PRIORITY=1`` — returns input unchanged.
    """
    if is_mechanism_disabled(Mechanism.VALUE_PRIORITY):
        return candidates
    if not candidates or len(candidates) < _MIN_RERANK_CANDIDATES:
        return candidates

    for c in candidates:
        base = c.get("score", 0.0) or 0.0
        value = c.get("value")
        if value is None:
            continue  # no value signal — leave score untouched
        c["score"] = retrieval_priority(base, value, weight=weight)

    candidates.sort(key=lambda c: c.get("score", 0.0), reverse=True)
    return candidates


# source: ADR-0235


def goal_maintenance_rerank(
    candidates: list[dict[str, Any]],
    goal: Any,
) -> list[dict[str, Any]]:
    """Nudge each candidate's score by its relevance to the active goal (A3).

    ``goal`` is a ``goal_maintenance.GoalVector`` (from pg_recall._get_active
    _goal). When it is inactive (no task in play) this is a strict identity —
    membership and order are unchanged, matching the behavior with no goal at
    all. When active, each candidate's score is scaled by
    ``goal_maintenance.goal_recall_multiplier`` (1.0 for off-task candidates,
    up to 1 + weight for fully goal-relevant ones) and the list is re-sorted.

    Disabled when ``CORTEX_ABLATE_GOAL_MAINTENANCE=1`` — returns input
    unchanged. No-op on fewer than two candidates.
    """
    if is_mechanism_disabled(Mechanism.GOAL_MAINTENANCE):
        return candidates
    if not candidates or len(candidates) < _MIN_RERANK_CANDIDATES:
        return candidates
    if goal is None or not goal_vector_is_active(goal):
        return candidates

    for c in candidates:
        base = c.get("score", 0.0) or 0.0
        mult = goal_recall_multiplier(
            goal,
            c.get("content", "") or "",
            entities=c.get("entities"),
            directory=c.get("directory", "") or "",
        )
        if mult != 1.0:
            c["score"] = base * mult

    candidates.sort(key=lambda c: c.get("score", 0.0), reverse=True)
    return candidates


# source: ADR-0235


def attentional_focus_rerank(
    candidates: list[dict[str, Any]],
    query: str,
    *,
    weight: float = 0.15,
) -> list[dict[str, Any]]:
    """Nudge each candidate's score by its top-down+salience attention (A1).

    source: ADR-0235

    Disabled when ``CORTEX_ABLATE_ATTENTIONAL_CONTROL=1`` — returns input
    unchanged. No-op on fewer than two candidates.
    """
    if is_mechanism_disabled(Mechanism.ATTENTIONAL_CONTROL):
        return candidates
    if not candidates or len(candidates) < _MIN_RERANK_CANDIDATES:
        return candidates

    n = len(candidates)
    # Map recall-candidate fields onto the item shape allocate_attention reads
    # (content + optional importance/valence). Candidates carry the stored
    # affect under ``emotional_valence``; the pure pass expects ``valence``.
    items = [
        {
            "content": c.get("content", "") or "",
            "importance": c.get("importance", 0.0) or 0.0,
            "valence": c.get("emotional_valence", 0.0) or 0.0,
        }
        for c in candidates
    ]
    # capacity = n → the focus set spans all candidates; we use only the
    # per-item weights as a soft re-weight, never truncating recall.
    alloc = allocate_attention(query, items, capacity=n)
    baseline = 1.0 / n
    # source: ADR-0235

    for c, attn in zip(candidates, alloc.weights, strict=True):
        base = c.get("score", 0.0) or 0.0
        c["score"] = base * (1.0 + weight * (attn - baseline))

    candidates.sort(key=lambda c: c.get("score", 0.0), reverse=True)
    return candidates


# source: ADR-0235


def reconsolidation_apply(
    candidates: list[dict[str, Any]],
    query: str,
    store: Any,
    *,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    """Apply reconsolidation to the top-K retrieved candidates.

    source: ADR-0235

    Disabled when ``CORTEX_ABLATE_RECONSOLIDATION=1`` — returns input
    unchanged with zero store writes. The same env var is also honored
    inside `decide_action`; this top-level guard skips the per-candidate
    iteration and store calls entirely when ablated.

    Store contract — uses only methods already on ``PgMemoryStore``:
      - ``bump_heat_raw(memory_id, new_heat_base)`` for the heat delta
      - ``update_memory_access(memory_id)`` for last_accessed + access_count
      - ``update_memory_emotional_valence(memory_id, valence)`` (optional)

    source: ADR-0235
    """
    if is_mechanism_disabled(Mechanism.RECONSOLIDATION):
        return candidates
    if not candidates:
        return candidates
    if store is None:
        return candidates

    q_valence = vader_compound(query) if query else 0.0
    q_tokens: set[str] = {
        t.strip(".,!?;:()[]{}\"'`").lower()
        for t in (query or "").split()
        if len(t) > _SHORT_TOKEN_MAX_LEN
    }

    limit = len(candidates) if top_k is None else min(top_k, len(candidates))
    has_bump = hasattr(store, "bump_heat_raw")
    has_access = hasattr(store, "update_memory_access")
    has_valence = hasattr(store, "update_memory_emotional_valence")

    for c in candidates[:limit]:
        try:
            outcome = compute_reconsolidation_action(
                c,
                query,
                embedding_similarity=None,
                current_directory="",
                context_tokens=q_tokens,
                query_valence=q_valence,
            )
        except Exception:  # noqa: BLE001 — source: ADR-0235
            continue

        if outcome.action == "none" and outcome.heat_delta == 0.0:
            continue

        # source: ADR-0235

        rewards_retrieval = outcome.heat_delta > 0.0 and not is_trusted_at_read(
            str(c.get("capture_origin", ""))
        )
        if has_bump and outcome.heat_delta != 0.0 and not rewards_retrieval:
            try:
                cur_heat = float(c.get("heat", 0.5) or 0.5)
                new_heat = max(0.0, min(1.0, cur_heat + outcome.heat_delta))
                store.bump_heat_raw(c["memory_id"], new_heat)
                c["heat"] = new_heat  # reflect in candidate for downstream use
            except Exception as exc:  # noqa: BLE001
                silent_failure.note("recall_pipeline.heat_writeback", exc)

        # last_accessed + access_count refresh.
        if has_access and outcome.update_last_accessed:
            try:
                store.update_memory_access(c["memory_id"])
            except Exception as exc:  # noqa: BLE001
                silent_failure.note("recall_pipeline.access_writeback", exc)

        # source: ADR-0235

        if has_valence and outcome.valence_delta != 0.0:
            try:
                cur_val = float(c.get("emotional_valence", 0.0) or 0.0)
                new_val = max(-1.0, min(1.0, cur_val + outcome.valence_delta))
                store.update_memory_emotional_valence(c["memory_id"], new_val)
                c["emotional_valence"] = new_val
            except Exception as exc:  # noqa: BLE001
                silent_failure.note("recall_pipeline.valence_writeback", exc)

    return candidates


# source: ADR-0235


def mood_congruent_rerank(
    candidates: list[dict[str, Any]],
    user_mood: float | None,
    *,
    blend_beta: float | None = None,
) -> list[dict[str, Any]]:
    """Rerank by user-mood ↔ candidate-valence congruence.

    ``user_mood`` is a float in [-1, +1] representing the user's current
    affective state (e.g., set by an upstream emotion classifier or a
    manual ``checkpoint`` annotation). When ``None``, the stage no-ops:
    we do NOT fabricate a mood signal in the absence of one.

    source: ADR-0235

    Disabled when ``CORTEX_ABLATE_MOOD_CONGRUENT_RERANK=1`` — returns
    input unchanged. Distinct from EMOTIONAL_RETRIEVAL (which uses the
    query text's inferred valence).

    source: ADR-0235"""
    if blend_beta is None:
        blend_beta = _tuning_float("CORTEX_MOOD_CONGRUENT_BETA", 0.15)
    if is_mechanism_disabled(Mechanism.MOOD_CONGRUENT_RERANK):
        return candidates
    if user_mood is None or not candidates:
        return candidates

    user_mood_f = float(user_mood)

    def _distance(c: dict[str, Any]) -> float:
        c_v = c.get("emotional_valence", 0.0) or 0.0
        return abs(float(c_v) - user_mood_f)

    by_match = sorted(enumerate(candidates), key=lambda x: _distance(x[1]))
    mech_ranks = {
        candidates[i]["memory_id"]: rank for rank, (i, _) in enumerate(by_match)
    }
    return _rrf_blend(candidates, mech_ranks, blend_beta)


# source: ADR-0235


def conflict_monitor_rerank(
    candidates: list[dict[str, Any]],
    store: Any = None,
) -> list[dict[str, Any]]:
    """Detect conflict in the retrieved set and demote the losing memory (A2).

    source: ADR-0235

    Disabled when ``CORTEX_ABLATE_CONFLICT_MONITOR=1`` — returns input
    unchanged. No-op on fewer than two candidates or when conflict is below
    threshold. Never raises: any failure inside the pass leaves the candidate
    list untouched (non-load-bearing — conflict monitoring refines ranking, it
    is not required for a correct recall).

    ``store`` is accepted for signature parity with the other post-WRRF stages
    and future store-backed conflict signals; it is unused today (the scalar is
    computed entirely from the candidate dicts).
    """
    if is_mechanism_disabled(Mechanism.CONFLICT_MONITOR):
        return candidates
    if not candidates or len(candidates) < _MIN_RERANK_CANDIDATES:
        return candidates

    try:
        assessment = conflict_monitor.assess_conflict(candidates)
        if not assessment.high:
            return candidates

        # Route the competing set to the existing claim resolver (pure planning;
        # empty for plain memories without typed-claim metadata).
        plans = conflict_monitor.route_to_resolver(candidates)

        # Demote the losing memory and re-sort.
        candidates = conflict_monitor.apply_downweight(candidates, assessment)

        if plans and candidates:
            # source: ADR-0235

            candidates[0].setdefault("conflict_plans", []).extend(plans)
            candidates[0]["conflict_assessment"] = (
                conflict_monitor.conflict_assessment_as_dict(assessment)
            )
    except Exception:  # noqa: BLE001 — source: ADR-0235
        return candidates

    return candidates
