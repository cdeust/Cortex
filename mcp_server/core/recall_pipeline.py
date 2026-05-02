"""Post-WRRF recall pipeline stages — paper-first-class reordering steps.

Each stage takes a `candidates` list (the output of the PG WRRF fusion) and
returns a possibly-reordered/expanded list. Stages are gated by
``is_mechanism_disabled`` so an ablation run with
``CORTEX_ABLATE_<MECH>=1`` returns the input unchanged.

Blending strategy: Reciprocal Rank Fusion (Cormack, Clarke & Buettcher,
SIGIR 2009 — "Reciprocal Rank Fusion outperforms Condorcet and individual
rank learning methods"). Each mechanism contributes a rank vector; we
combine the existing WRRF rank with the new mechanism's rank via
``score = (1-beta)/(k+rel_rank) + beta/(k+mech_rank)`` with k=60 (paper
default) and beta in [0.0, 0.5] (small enough that the existing WRRF
ranking dominates but the new signal can break near-ties and inject
high-relevance candidates from the spreading-activation expansion).

Dendritic clusters use a multiplicative factor instead of a rank because
Poirazi, Brannon & Mel (2003) describe soma output as a multiplicative
nonlinearity ``g(x) = scale * x / (1 + offset * exp(-steepness * x))``,
not a rank fusion. We apply a bounded factor in [0.9, 1.1] so the
modulation never dominates the underlying retrieval score.

Pure business logic — operates on candidate dicts, takes store/embeddings
as parameters. No I/O of its own; the store calls go through the same
abstractions used by ``pg_recall.recall``.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core.ablation import Mechanism, is_mechanism_disabled

# RRF constant from Cormack et al. (SIGIR 2009). The paper recommends k=60
# as a robust default across heterogeneous rankers; the same constant is
# used elsewhere in pg_recall (_chronological_rerank).
_RRF_K: int = 60

# Per-mechanism blend weights. Small enough that WRRF still dominates;
# large enough that the new signal breaks ties and surfaces near-misses.
# These are engineering defaults, not paper-prescribed — they bound the
# perturbation each post-WRRF stage can inflict on the candidate order.
# When a mechanism's smoke test shows zero delta on a real corpus, raise
# its beta in 0.05 increments and re-run; do NOT remove the wiring.
_HOPFIELD_BETA: float = 0.30
_HDC_BETA: float = 0.20
_SA_BETA: float = 0.25

# Dendritic multiplicative range — bounded perturbation from Poirazi (2003)
# soma scale of 0.96. We use [1 - DELTA, 1 + DELTA] so a 1.0 baseline
# (no cluster match) leaves the score unchanged, while high-affinity
# matches get a +DELTA bump and conflicting branches get -DELTA.
_DENDRITIC_DELTA: float = 0.10


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

    Source: Cormack, Clarke & Buettcher (SIGIR 2009).
    """
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


# ── HOPFIELD stage ──────────────────────────────────────────────────────
# Ramsauer et al. (2021), "Hopfield Networks Is All You Need." ICLR 2021.
# Modern Hopfield retrieval = softmax(beta * X · query) attention.


def hopfield_complete(
    candidates: list[dict[str, Any]],
    q_emb: bytes | None,
    store: Any,
    embedding_dim: int,
    *,
    hopfield_beta: float = 8.0,
    blend_beta: float = _HOPFIELD_BETA,
) -> list[dict[str, Any]]:
    """Reorder candidates by Hopfield attention rank, RRF-blended with WRRF.

    The Hopfield pattern matrix is built from the candidates' own embeddings
    (fetched from the store in **one bulk PG call**, not N per-candidate
    round-trips). Hopfield attention then ranks them by
    ``softmax(beta * X · query)``; we blend that rank with the WRRF rank.

    Bulk fetch path: ``store.get_embeddings_for_memories(ids)`` →
    ``WHERE id = ANY(%s)`` single SELECT, returns ``{id: embedding}``.
    Falls back to per-id ``get_memory`` only if the bulk method is absent
    (e.g., older store stub in tests). At top_k=30 this turns 30 round
    trips into 1 — paper-claim-bearing because Hopfield wall-time was
    untracked under production load before this refactor.

    Source: Ramsauer et al. (2021), "Hopfield Networks Is All You Need."
    ICLR 2021 — softmax attention as modern Hopfield retrieval.

    Disabled when ``CORTEX_ABLATE_HOPFIELD=1`` — returns input
    unchanged. The same env var is also checked inside
    ``hopfield.retrieve``; this top-level guard avoids the round-trip
    embedding fetch when ablated.
    """
    if is_mechanism_disabled(Mechanism.HOPFIELD):
        return candidates
    if not candidates or q_emb is None:
        return candidates

    from mcp_server.core import hopfield

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


# ── HDC stage ───────────────────────────────────────────────────────────
# Kanerva (2009), "Hyperdimensional Computing." Cognitive Computation 1(2).
# Bipolar (+1/-1) random hypervectors with bind/bundle algebra.


def hdc_rerank(
    candidates: list[dict[str, Any]],
    query: str,
    *,
    blend_beta: float = _HDC_BETA,
) -> list[dict[str, Any]]:
    """Reorder candidates by HDC similarity, RRF-blended with WRRF.

    Each candidate's content is encoded as a bipolar hypervector
    (bundle of word atoms + bigram binds); HDC similarity = dot/dim.

    Disabled when ``CORTEX_ABLATE_HDC=1`` —
    returns input unchanged. The same guard fires in
    ``compute_hdc_scores``; this top-level early-return avoids the
    encoding cost when ablated.
    """
    if is_mechanism_disabled(Mechanism.HDC):
        return candidates
    if not candidates:
        return candidates

    from mcp_server.core.hdc_encoder import compute_hdc_scores

    pairs = [(c["memory_id"], c.get("content", "") or "") for c in candidates]
    hdc = compute_hdc_scores(query, pairs, threshold=-1.0)  # keep all ranks
    if not hdc:
        return candidates

    mech_ranks = {mid: rank for rank, (mid, _) in enumerate(hdc)}
    return _rrf_blend(candidates, mech_ranks, blend_beta)


# ── SPREADING_ACTIVATION stage ─────────────────────────────────────────
# Collins & Loftus (1975), "A Spreading-Activation Theory of Semantic
# Processing." Psychological Review 82(6). Implementation: BFS over the
# entity graph with exponential decay by depth and convergent summation.


def spreading_activation_expand(
    candidates: list[dict[str, Any]],
    query: str,
    store: Any,
    *,
    decay: float = 0.65,
    threshold: float = 0.1,
    max_depth: int = 3,
    max_results: int = 50,
    min_heat: float = 0.05,
    blend_beta: float = _SA_BETA,
) -> list[dict[str, Any]]:
    """Expand the candidate pool with SA-reachable memories, then RRF blend.

    Calls the ``spread_activation_memories`` PL/pgSQL stored procedure
    (server-side BFS over the entity graph). Memories already in
    ``candidates`` get an SA rank; new ones are appended at the bottom
    of the candidate list before RRF blending — so a strongly SA-active
    memory absent from the WRRF top-K can still surface.

    Disabled when ``CORTEX_ABLATE_SPREADING_ACTIVATION=1`` — returns
    input unchanged. The store-side ``spread_activation_memories`` PL/pgSQL
    is not aware of the env var, so the gate must live here.
    """
    if is_mechanism_disabled(Mechanism.SPREADING_ACTIVATION):
        return candidates
    if not candidates:
        return candidates
    if not hasattr(store, "spread_activation_memories"):
        return candidates

    from mcp_server.core.query_decomposition import extract_query_entities

    terms = list(
        set(extract_query_entities(query) + [w for w in query.split() if len(w) > 2])
    )
    if not terms:
        return candidates

    try:
        sa = store.spread_activation_memories(
            query_terms=terms,
            decay=decay,
            threshold=threshold,
            max_depth=max_depth,
            max_results=max_results,
            min_heat=min_heat,
        )
    except Exception:
        return candidates
    if not sa:
        return candidates

    existing_ids = {c["memory_id"] for c in candidates}
    expanded = list(candidates)

    # Append SA-discovered memories not already in the candidate pool.
    for mid, _act in sa:
        if mid in existing_ids:
            continue
        if not hasattr(store, "get_memory"):
            continue
        mem = store.get_memory(mid)
        if not mem:
            continue
        expanded.append(
            {
                "memory_id": mid,
                "content": mem.get("content", ""),
                "score": 0.0,  # will be set by RRF blend
                "heat": mem.get("heat", 0.0),
                "domain": mem.get("domain", ""),
                "tags": mem.get("tags", []),
                "created_at": mem.get("created_at", ""),
                "_sa_injected": True,
            }
        )
        existing_ids.add(mid)

    mech_ranks = {mid: rank for rank, (mid, _act) in enumerate(sa)}
    return _rrf_blend(expanded, mech_ranks, blend_beta)


# ── DENDRITIC_CLUSTERS stage ────────────────────────────────────────────
# Poirazi, Brannon & Mel (2003), "Pyramidal Neuron as a Two-Layer Neural
# Network." Neuron 37:989-999. Branch subunit + soma nonlinearity.
# Cluster admission via Jaccard (Kastellakis 2015 — engineering proxy).


def _candidate_entities(c: dict[str, Any]) -> set[str]:
    """Extract a coarse entity-token set from a candidate's content."""
    content = (c.get("content") or "").lower()
    # Token-level proxy for entity overlap — same shape used by
    # dendritic_clusters.compute_branch_affinity (Jaccard over sets).
    return {t.strip(".,!?;:()[]{}\"'`") for t in content.split() if len(t) > 2}


def _candidate_tags(c: dict[str, Any]) -> set[str]:
    """Normalize a candidate's tag set for Jaccard."""
    tags = c.get("tags") or []
    if isinstance(tags, str):
        return {tags}
    return {str(t) for t in tags}


def _resolve_query_entity_ids(query: str, store: Any) -> set[int]:
    """Resolve query entities (CamelCase / paths / backticks) to entity_ids.

    Constant-cost per recall (typical query has 0-5 such entities), so
    this stays a small loop of ``get_entity_by_name`` calls, not a
    per-candidate scan. Returns the empty set if nothing resolves —
    callers must then fall back to the token-Jaccard proxy.
    """
    from mcp_server.core.query_decomposition import extract_query_entities

    if not hasattr(store, "get_entity_by_name"):
        return set()
    ids: set[int] = set()
    for name in extract_query_entities(query):
        row = store.get_entity_by_name(name)
        if row and row.get("id") is not None:
            ids.add(int(row["id"]))
    return ids


def dendritic_modulate(
    candidates: list[dict[str, Any]],
    query: str,
    store: Any = None,
    *,
    delta: float = _DENDRITIC_DELTA,
) -> list[dict[str, Any]]:
    """Apply branch-affinity multiplicative modulation to candidate scores.

    Computes weighted Jaccard affinity (0.7 entity + 0.3 tag — same
    weights as ``dendritic_clusters.compute_branch_affinity``).
    The score is multiplied by ``1 + delta * (2 * affinity - 1)`` so
    affinity 0.0 → factor 1 - delta, affinity 0.5 → factor 1.0,
    affinity 1.0 → factor 1 + delta.

    **Entity-set source.** When ``store`` exposes
    ``get_entity_ids_for_memories`` AND the query resolves to ≥1 known
    ``entity_id``, the affinity is computed on the **real entity graph**
    (the ``memory_entities`` join) — Jaccard 1912 set similarity over
    integer ids. This is the faithful model of Kastellakis (2015) branch
    admission. One bulk PG round trip; no per-candidate query.

    Falls back to the prior content-token Jaccard proxy when (a) the
    store lacks the bulk method (test stub), or (b) the query has zero
    resolvable entities — natural-language queries with no CamelCase /
    paths / backticks. The fallback is documented in
    ``dendritic_clusters.compute_branch_affinity`` as an engineering
    proxy.

    Sources:
      - Poirazi, Brannon & Mel (2003). *Pyramidal Neuron as a Two-Layer
        Neural Network.* Neuron 37:989-999. (Multiplicative soma.)
      - Jaccard, P. (1912). *The Distribution of the Flora in the Alpine
        Zone.* New Phytologist 11(2):37-50. (Set similarity.)
      - Kastellakis et al. (2015). *Synaptic Clustering within Dendrites.*
        Prog. Neurobiol. 126:19-35. (Cluster admission via overlap.)

    Disabled when ``CORTEX_ABLATE_DENDRITIC_CLUSTERS=1`` — returns input
    unchanged. Bounded perturbation: max ±delta per candidate, so the
    modulation can break near-ties but never dominates the underlying
    retrieval score (Poirazi 2003 soma scale = 0.96, comparable bound).
    """
    if is_mechanism_disabled(Mechanism.DENDRITIC_CLUSTERS):
        return candidates
    if not candidates or delta <= 0.0:
        return candidates

    from mcp_server.shared.similarity import jaccard_similarity

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
        t.strip(".,!?;:()[]{}\"'`").lower() for t in query.split() if len(t) > 2
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
