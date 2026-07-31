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

import logging
import os as _os
from typing import Any

from mcp_server.core.ablation import Mechanism, is_mechanism_disabled
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

# RRF constant from Cormack et al. (SIGIR 2009). The paper recommends k=60
# as a robust default across heterogeneous rankers; the same constant is
# used elsewhere in pg_recall (_chronological_rerank).
_RRF_K: int = 60

# Tokens at or below this length are dropped by the token-proxy filters in
# this module (query terms, candidate entities, tag Jaccard).
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_SHORT_TOKEN_MAX_LEN: int = 2

# source: structural — a rerank stage no-ops on fewer than two candidates
# (nothing to reorder); each stage docstring states "No-op on fewer than
# two candidates".
_MIN_RERANK_CANDIDATES: int = 2

# source: adjacent comment at _resolve_query_entity_ids — only tokens of
# length ≥ 4 are tried, to avoid swamping the entity index with junk lookups.
_ENTITY_FALLBACK_TOKEN_MIN_LEN: int = 4


def _env_float(name: str, default: float) -> float:
    """Read a float from ``os.environ[name]`` falling back to ``default``.

    Used by the blend-weight calibration sweep (`benchmarks/lib/blend_weight_sweep.py`)
    to override per-cell without rebuilding the module. Source: standard
    benchmark-time config injection per `docs/provenance/verification-protocol.md`
    §reproducibility (manifest sidecar). Malformed values fall back to the
    default — a calibration cell with `CORTEX_HOPFIELD_BETA=foo` is a bug,
    not a runtime crash, and the manifest will record what was *actually*
    used (logged separately by the harness).
    """
    raw = _os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# Per-mechanism blend weights. Small enough that WRRF still dominates;
# large enough that the new signal breaks ties and surfaces near-misses.
# These are engineering defaults, not paper-prescribed — they bound the
# perturbation each post-WRRF stage can inflict on the candidate order.
# When a mechanism's smoke test shows zero delta on a real corpus, raise
# its beta in 0.05 increments and re-run; do NOT remove the wiring.
#
# CALIBRATION OVERRIDE. The five blend constants and the dendritic delta
# below are env-var-overridable via ``CORTEX_<NAME>``. The harness at
# ``benchmarks/lib/blend_weight_sweep.py`` sets these per cell and runs
# LongMemEval-S to pick the optima documented in
# ``docs/provenance/blend-weight-calibration.md``. If unset, the engineering defaults
# below stand.
#
# Calibration outcome (task #50, Phase A — 17-cell CCD, n=50 LongMemEval-S,
# 2026-05-02): all four perception-side knobs are confirmed near-optimum at
# their engineering defaults. Center cell (0.30, 0.20, 0.25, 0.10) is the
# unique plateau winner at MRR=0.84, R@10=0.94. Marginal effects 0.035–0.045
# confirm the knobs DO affect retrieval (not no-ops); the defaults happen to
# be the optimal levels. See docs/provenance/blend-weight-calibration.md Results §A.
# engineering default — confirmed near-optimum,
# docs/provenance/blend-weight-calibration.md Results §HOPFIELD_BETA
_HOPFIELD_BETA: float = _env_float("CORTEX_HOPFIELD_BETA", 0.30)
# engineering default — confirmed near-optimum,
# docs/provenance/blend-weight-calibration.md Results §HDC_BETA
_HDC_BETA: float = _env_float("CORTEX_HDC_BETA", 0.20)
# engineering default — confirmed near-optimum,
# docs/provenance/blend-weight-calibration.md Results §SA_BETA
_SA_BETA: float = _env_float("CORTEX_SA_BETA", 0.25)

# Dendritic multiplicative range — bounded perturbation from Poirazi (2003)
# soma scale of 0.96. We use [1 - DELTA, 1 + DELTA] so a 1.0 baseline
# (no cluster match) leaves the score unchanged, while high-affinity
# matches get a +DELTA bump and conflicting branches get -DELTA.
# engineering default — confirmed near-optimum,
# docs/provenance/blend-weight-calibration.md Results §DENDRITIC_DELTA
_DENDRITIC_DELTA: float = _env_float("CORTEX_DENDRITIC_DELTA", 0.10)

# Emotional / mood-congruent rerank blend weights.
# Bower (1981) "Mood and Memory," Am. Psychologist 36(2) does not prescribe
# a numeric blend weight; the paper's claim is qualitative (mood-congruent
# recall is faster/more accurate than incongruent), so the magnitude is set
# conservatively below the perception-side stages.
#
# Calibration outcome (task #50, Phase B — 25-cell 5×5 grid, n=30
# LongMemEval-S, 2026-05-02): both affect-side knobs showed zero observable
# effect on LongMemEval-S (all 25 cells tied at MRR=0.84, marginal=0.0).
# This is a genuine null on this benchmark, driven by upstream gates:
#   • EMOTIONAL_RETRIEVAL stage no-ops because LME-S queries are factual/
#     neutral (VADER compound < _EMOTIONAL_QUERY_VALENCE_FLOOR=0.10, see
#     floor check inside emotional_retrieval_rerank below).
#   • MOOD_CONGRUENT_RERANK stage no-ops because PgMemoryStore has no
#     get_user_mood() adapter (task #54). _get_user_mood(store) at
#     pg_recall.py returns None and the stage short-circuits.
# Constants are kept at the conservative engineering defaults for the
# benefit of benchmarks that DO exercise these gates (emotion-laden corpora,
# user-mood-aware deployments).
# engineering default — no observable effect on LongMemEval-S (upstream
# VADER gate); docs/provenance/blend-weight-calibration.md Results
# §EMOTIONAL_RETRIEVAL_BETA
_EMOTIONAL_RETRIEVAL_BETA: float = _env_float("CORTEX_EMOTIONAL_RETRIEVAL_BETA", 0.20)
# engineering default — no observable effect on LongMemEval-S (no
# user-mood adapter); docs/provenance/blend-weight-calibration.md Results
# §MOOD_CONGRUENT_BETA
_MOOD_CONGRUENT_BETA: float = _env_float("CORTEX_MOOD_CONGRUENT_BETA", 0.15)

# Below this absolute compound-valence value the query is treated as
# emotionally neutral and the EMOTIONAL_RETRIEVAL stage no-ops. VADER
# (Hutto & Gilbert, ICWSM 2014) §4 reports |compound| ≥ 0.05 as a useful
# positive/negative cutoff for short text; we use 0.10 so that single
# weakly-loaded tokens do not flip the rerank.
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


# ── FAMILIARITY_TRIAGE stage (C2 recollection vs. familiarity) ──────────
# Yonelinas (2002), J. Mem. Lang. 46(3):441-517; Diana, Yonelinas & Ranganath
# (2007), Trends Cogn. Sci. 11(9):379-386. Familiarity is a fast, a-contextual
# prior-exposure scalar (perirhinal); recollection is slow contextual
# reconstruction (hippocampal). Two-stage retrieval — cheap recall + expensive
# rerank — is the standard IR analogue. This stage runs EARLY, before the
# expensive post-WRRF rerank chain, and reads a lightweight familiarity signal
# (MAX query↔candidate cosine similarity, NO context assembly) so an
# overwhelmingly-familiar query can OPTIONALLY skip full reconstruction.
#
# PARITY GUARANTEE: by default the stage only ANNOTATES each candidate with its
# per-candidate familiarity and returns them in unchanged order/membership; the
# recollection short-circuit is opt-in (allow_shortcut) and fires only on an
# overwhelming, single-dominant vector hit. With the default recall() the full
# recollection chain always runs, so recall output is byte-for-byte unchanged
# apart from the added annotation key.


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

      - ``candidates`` — annotated with per-candidate ``familiarity`` (order and
        membership UNCHANGED);
      - ``signal`` — the set-level FamiliaritySignal (max/mean/margin/method);
      - ``recollection_needed`` — the decision (default assumption True);
      - ``shortcut`` — True only when ``allow_shortcut`` AND familiarity is an
        overwhelming single-dominant vector hit.

    Disabled when ``CORTEX_ABLATE_DUAL_PROCESS=1`` — returns a TriageResult that
    leaves the candidates untouched (no annotation), recollection_needed=True,
    shortcut=False, so the full recollection chain always runs (identity).

    Returns a ``dual_process_retrieval.TriageResult`` (NOT a bare list) because
    the caller needs the shortcut decision, not just a reordering. It performs no
    reordering itself — recollection is the pre-existing rerank chain in
    ``pg_recall.recall``; this stage only gates whether that chain runs.

    Honesty note: familiarity here is the max-cosine-similarity heuristic, not a
    trained dual-process model; see dual_process_retrieval.py module docstring.

    Sources:
      - Yonelinas (2002). J. Mem. Lang. 46(3):441-517.
      - Diana, Yonelinas & Ranganath (2007). Trends Cogn. Sci. 11(9):379-386.
    """

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
        except Exception:  # noqa: BLE001 — non-load-bearing per-candidate
            sims.append(0.0)

    return dpr.triage(
        candidates,
        sims,
        allow_shortcut=allow_shortcut,
        method=dpr.METHOD_VECTOR,
    )


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


# Non-silent failure state for the SA channel (mirrors reranker.py's
# _flashrank_failed pattern, commit bb1c581f, 2026-07-11 incident: a bare
# `except Exception: return candidates` here swallowed the SA channel's
# missing-WITH-RECURSIVE bug for the channel's entire lifetime with zero
# log signal — see pg_schema.py::SPREAD_ACTIVATION_MEMORIES_FN docstring
# and ADR-0054). Logged once per process on first failure to avoid log
# spam; state stays introspectable via ``spreading_activation_status()``
# for preflight/bench-harness checks, same contract as reranker_status().
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

    Shared by both SA injection modes (augment, tail) so the ablation
    check, domain-scoping wiring, and failure telemetry stay in exactly
    one place. Returns ``[]`` (never raises) on ablation, no extractable
    terms, a store missing ``spread_activation_memories``, or a store
    call failure -- callers treat an empty return as "inject nothing,
    leave candidates as-is".
    """
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
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        # First-failure-only logging (reranker.py precedent, bb1c581f):
        # a per-query stage like this one can be called on every recall,
        # so logging every occurrence would spam at the same rate as the
        # calls themselves without adding information beyond "still
        # broken" -- state stays introspectable via
        # spreading_activation_status() for callers (bench preflight,
        # health checks) that need to distinguish never-attempted from
        # broken-and-suppressed.
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


# Contract (incident 2026-07-11, garde x3 bench, LongMemEval crash at
# pg_recall.py::_chronological_rerank -- ADR-0054 addendum): an
# injected candidate MUST carry the same field set, with the same
# Python types, as a WRRF candidate from store.recall_memories() --
# its RETURNS TABLE columns are memory_id/content/score/heat/domain/
# created_at/store_type/tags/importance/surprise_score/
# emotional_valence/source/value/source_attribution. Two prior bugs,
# both from building this dict as a curated 6-field subset of `mem`
# instead of the full common contract:
#   1. created_at came from store.get_memory() (normalized to an ISO
#      string by _normalize_memory_row) while WRRF candidates carried
#      a raw psycopg datetime.datetime -- sorted() on a mixed list
#      raised TypeError. Fixed at the true source: pg_store.py's
#      recall_memories() now normalizes too (see
#      _isoformat_datetime_fields) -- both sides are str.
#   2. store_type/source/source_attribution/importance/surprise_score/
#      emotional_valence/value were silently ABSENT from injected
#      candidates even though store.get_memory() (SELECT * FROM
#      memories) already returns them -- a downstream consumer keyed
#      on `mem.get("source")` (recall_helpers.py's low-signal filter)
#      would silently misclassify every SA-injected candidate as
#      non-auto-capture regardless of its real source.
def _sa_candidate_from_memory(mid: int, mem: dict[str, Any]) -> dict[str, Any]:
    """Build a WRRF-contract-shaped candidate dict from a get_memory() row.

    Whitelist, not ``dict(mem)``: get_memory() is ``SELECT * FROM
    memories`` (every column, including internal state -- is_stale,
    compression_level, write_class, forgetting_pressure_accum,
    embedding, superseded_by_id, ...) while a WRRF candidate is exactly
    recall_memories()'s RETURNS TABLE (14 columns). Copying the full row
    would swap the missing-fields bug for a leaked-internal-fields one --
    this dict's KEY SET, not just each value's type, must match the
    WRRF contract.
    """
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
    blend_beta: float = _SA_BETA,
) -> list[dict[str, Any]]:
    """AUGMENT mode: expand the candidate pool with SA-reachable memories,
    then RRF blend (can reorder and outrank existing candidates).

    Calls the ``spread_activation_memories`` PL/pgSQL stored procedure
    (server-side BFS over the entity graph). Memories already in
    ``candidates`` get an SA rank; new ones are appended at the bottom
    of the candidate list before RRF blending — so a strongly SA-active
    memory absent from the WRRF top-K can still surface, and can move
    ABOVE existing candidates.

    Opt-in only (ADR-0054 addendum, 2026-07-11): this was the DEFAULT
    mode when spread_activation_memories first went live, and the garde
    x3 bench's first live measurement on LongMemEval showed it is NOT
    benchmark-neutral even with domain scoping applied -- MRR
    0.9166->0.9009 (floor 0.914 breach) against +0.002 R@10, because
    LongMemEval's ingestion legitimately creates entities INSIDE the
    query's own domain (8469 counted), so domain scoping alone does not
    stop this mode from reordering already-correct top candidates.
    ``pg_recall.recall()``'s default ``sa_mode="tail"`` uses
    ``spreading_activation_tail_fill`` instead (never reorders). This
    function remains available via ``sa_mode="augment"`` for future
    exploration (e.g. a unified_search-specific tuning campaign) but
    requires its own dedicated benchmark campaign before any default
    change -- "the guard wins; never lower the floor."

    Domain scoping (ADR-0054, decision 2026-07-11): the entity graph is
    shared across domains by design (see pg_schema.py module comment),
    but the final entity->memory mapping is scoped to ``domain`` by
    default — measured 52.8% cross-domain injection rate when unscoped
    (scratchpad/spread-activation-scoping-design.md §2.3). Set
    ``cross_domain=True`` to opt out explicitly and search the full
    graph regardless of domain (mirrors the existing
    ``include_globals`` opt-in pattern on ``recall_memories()``).

    Disabled when ``CORTEX_ABLATE_SPREADING_ACTIVATION=1`` — returns
    input unchanged.
    """
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
    """TAIL mode (default, ADR-0054 addendum): append SA-reachable
    memories ONLY to fill a short list up to ``top_k``. Never reorders,
    never re-scores, never touches an existing candidate.

    Precondition: ``candidates`` is the FINAL post-rerank list --
    ``pg_recall.py::recall()`` calls this LAST, after every reranking
    stage (FlashRank, VALUE_PRIORITY, CONFLICT_MONITOR, GOAL_MAINTENANCE,
    ATTENTIONAL_CONTROL, and the EVENT_ORDER chronological rerank), so an
    appended candidate can never be picked up by a later stage and moved.
    Postcondition: ``candidates == filled[:len(candidates)]`` (same
    dicts, same order, unchanged) and ``len(filled) <= top_k``; any
    appended item satisfies the same WRRF field contract as
    ``spreading_activation_expand``'s injections
    (``_sa_candidate_from_memory``).

    Benchmark-neutral by construction (garde x3 incident, 2026-07-11):
    when ``len(candidates) >= top_k`` (WRRF + reranking already filled
    the request) this returns ``candidates`` unchanged BEFORE making any
    store call -- zero I/O, zero effect, on any corpus dense enough to
    already fill top_k (LongMemEval, LoCoMo, BEAM all do). Value is
    preserved exactly where recall is sparse: small/cold domains and
    thin corpora that WRRF alone cannot fill to top_k.

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


# ── DENDRITIC_CLUSTERS stage ────────────────────────────────────────────
# Poirazi, Brannon & Mel (2003), "Pyramidal Neuron as a Two-Layer Neural
# Network." Neuron 37:989-999. Branch subunit + soma nonlinearity.
# Cluster admission via Jaccard (Kastellakis 2015 — engineering proxy).


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

    Two-stage resolution so dendritic Jaccard fires on natural-language
    queries (not just CamelCase / path / backtick patterns):

    1. ``extract_query_entities()`` — high-precision extraction of
       CamelCase, slash paths, backtick code spans (Poirazi et al.
       compatible: these are typically the entity-anchors a user writes).
    2. **Token fallback** — for every alphabetic token of length ≥ 4
       not already extracted, attempt ``get_entity_by_name(token)``.
       This catches natural-language anchors like "authentication" or
       "deployment" which the regex-extractor misses but which often
       canonicalize to a real entity_id in the production graph.

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

    # Stage 2: natural-language token fallback. Use the existing
    # stopword-aware keyword extractor (`shared/text.py::extract_keywords`)
    # which already filters function words; only try tokens of length ≥ 4
    # to avoid swamping the entity index with junk lookups.
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


# ── EMOTIONAL_RETRIEVAL stage ───────────────────────────────────────────
# Bower, G.H. (1981). "Mood and Memory." Am. Psychologist 36(2):129-148.
# Mood-congruent recall: candidates whose stored emotional valence matches
# the query's inferred valence are retrieved faster and more accurately.
# Engineering blend via RRF (Cormack et al. SIGIR 2009).


def emotional_retrieval_rerank(
    candidates: list[dict[str, Any]],
    query: str,
    *,
    blend_beta: float = _EMOTIONAL_RETRIEVAL_BETA,
    valence_floor: float = _EMOTIONAL_QUERY_VALENCE_FLOOR,
) -> list[dict[str, Any]]:
    """Rerank by query-valence ↔ candidate-valence congruence.

    Bower (1981): emotionally-congruent material is retrieved faster and
    more accurately than incongruent material. We infer the query's
    affective load via VADER (Hutto & Gilbert, ICWSM 2014), measure each
    candidate's stored ``emotional_valence`` distance from the query
    valence, then RRF-blend that rank with the WRRF rank.

    A neutral query (|valence| < ``valence_floor``) carries no congruence
    signal and the stage no-ops — RRF on a uniform rank would only
    add noise.

    Disabled when ``CORTEX_ABLATE_EMOTIONAL_RETRIEVAL=1`` — returns input
    unchanged. Distinct from MOOD_CONGRUENT_RERANK: this stage uses the
    *query's* valence (per-recall), not a session-level user mood state.

    Sources:
      - Bower, G.H. (1981). "Mood and Memory." Am. Psychologist 36(2).
      - Hutto, C.J. & Gilbert, E. (2014). "VADER: A Parsimonious Rule-based
        Model for Sentiment Analysis of Social Media Text." ICWSM 2014.
      - Cormack, Clarke & Buettcher (2009). RRF blend.
    """
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


# ── VALUE_PRIORITY stage (B2 RL value learning) ─────────────────────────
# Schultz, Dayan & Montague (1997); Sutton & Barto (1998). Each memory carries
# a learned scalar ``value`` in [0,1] that accrues via TD credit assignment from
# usefulness/session outcomes (see core.value_learning). A memory that has
# repeatedly contributed to good outcomes should surface slightly ahead of an
# equally-relevant but unproven one, and a repeatedly-unhelpful one slightly
# behind. Unlike the emotional/mood stages this is NOT an RRF rank blend but a
# small multiplicative nudge on the content-relevance score
# (value_learning.retrieval_priority: score' = score·(1 + w·(value − prior))),
# so value refines rather than reorders relevance. Runs AFTER FlashRank so it
# adjusts the final content-relevance score, and is deliberately weak (w=0.15)
# so it never overrides a strong content match.


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


# ── GOAL_MAINTENANCE stage (A3 goal / task-set maintenance) ─────────────
# Miller & Cohen (2001), Annu. Rev. Neurosci. 24:167-202 — prefrontal cortex
# holds an active task-set that biases processing toward goal-relevant
# information. Here: while a goal is active (a GoalVector promoted from the
# store's active prospective triggers, see pg_recall._get_active_goal), each
# candidate's content-relevance score is scaled by a small multiplicative gain
# ``1 + weight·goal_relevance`` (goal_maintenance.goal_recall_multiplier) so
# goal-relevant memories surface slightly ahead of equally-relevant off-task
# ones. Like VALUE_PRIORITY this is a multiplicative nudge, NOT an RRF rank
# blend, and deliberately weak (weight 0.15) so it refines rather than reorders
# relevance. No active goal / off-task candidate => gain 1.0 => list unchanged.
#
# DESIGN INFERENCE: the goal-match is a deterministic keyword/entity/directory
# overlap re-weight promoted from the prospective trigger surface, not a learned
# PFC task-set controller (see goal_maintenance module docstring).


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


# ── ATTENTIONAL_CONTROL stage (A1 central-executive read-side) ──────────
# Baddeley (2003) central executive; Posner & Petersen (1990) attention
# spotlight; Cowan (2001) focus capacity. A1 already provides the pure
# attention-allocation pass (attentional_control.allocate_attention): a
# top-down lexical-relevance + bottom-up salience score per item, softmaxed
# (temperature-scaled) into an attention distribution. Here we run that SAME
# pass over the recall candidate set with the recall query as the top-down cue,
# then apply a small multiplicative nudge score·(1 + weight·(attn − baseline))
# to each candidate, where attn is its attention weight and baseline = 1/n (the
# uniform weight). Like VALUE_PRIORITY / GOAL_MAINTENANCE this is a bounded
# multiplicative nudge, NOT an RRF rank blend.
#
# CRITICAL: the candidate set is NOT truncated to the Cowan FOCUS_CAPACITY
# ceiling. That ceiling bounds the working-set spotlight (sensory_buffer.focus),
# NOT how many memories recall returns; here attention is used only as a SOFT
# re-weight over the FULL candidate set (allocate_attention is called with
# capacity = n so its focus set spans every candidate, and we read only the
# per-item weights). When attention is uniform (no query overlap and equal
# salience → equal logits → uniform softmax) every candidate's weight equals
# baseline, so every factor is exactly 1.0 and neither scores nor order change —
# the behavior-preserving default. Reuses allocate_attention; the softmax is NOT
# reimplemented here.
#
# DESIGN INFERENCE: the top-down term is lexical query/candidate overlap plus
# fixed-constant salience (attentional_control), not a learned attention
# controller — see the attentional_control module honesty note.


def attentional_focus_rerank(
    candidates: list[dict[str, Any]],
    query: str,
    *,
    weight: float = 0.15,
) -> list[dict[str, Any]]:
    """Nudge each candidate's score by its top-down+salience attention (A1).

    Runs ``attentional_control.allocate_attention`` over the FULL candidate set
    (capacity = ``len(candidates)`` so there is NO working-set truncation — the
    Cowan ceiling bounds the in-focus spotlight, not recall size) with ``query``
    as the top-down cue. Each candidate's score is scaled by
    ``1 + weight·(attn − baseline)`` where ``attn`` is its attention weight and
    ``baseline = 1/n`` the uniform weight, then the list is re-sorted.

    Behavior-preserving by default: when attention is uniform (no query overlap
    and equal salience) every weight equals ``baseline``, so every factor is
    exactly 1.0 and neither scores nor order change. The nudge is deliberately
    small (weight 0.15) so attention refines rather than reorders content
    relevance, and it REUSES A1's pure ``allocate_attention`` — the softmax is
    not reimplemented. The soft re-weight applies to every candidate; the recall
    result is never capped at ``FOCUS_CAPACITY``.

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
    # strict=True: allocate_attention always returns one weight per input
    # item (items has len(candidates) by construction above). Documented
    # equivalent mutant (coding-standards.md §12.1): allocate_attention's
    # own internal precondition (see attentional_control.py) makes this
    # length mismatch unreachable, so strict=True vs strict=False/None is
    # not observable through this call.
    for c, attn in zip(candidates, alloc.weights, strict=True):
        base = c.get("score", 0.0) or 0.0
        c["score"] = base * (1.0 + weight * (attn - baseline))

    candidates.sort(key=lambda c: c.get("score", 0.0), reverse=True)
    return candidates


# ── RECONSOLIDATION stage ──────────────────────────────────────────────
# Nader, Schafe & LeDoux (2000), Nature 406(6797). On retrieval a memory
# becomes labile and may be re-stored with modifications. Wired here as
# the final post-WRRF stage so the mutation reflects the FINAL ranking
# (i.e., what the user actually saw), not the raw WRRF output.
#
# This stage MUTATES the store (heat bump + last_accessed update +
# optional valence shift). All other post-WRRF stages are pure ranking.
# The mutation is bounded (heat_delta ∈ [-0.10, +0.05], valence_delta ∈
# [-0.10, +0.10] — see reconsolidation.compute_reconsolidation_action)
# and idempotent within a recall: each candidate is touched at most once.


def reconsolidation_apply(
    candidates: list[dict[str, Any]],
    query: str,
    store: Any,
    *,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    """Apply Nader-2000 reconsolidation to the top-K retrieved candidates.

    For each candidate (up to ``top_k``, default = all): compute the
    reconsolidation action via `compute_reconsolidation_action`, then
    apply the resulting heat / valence / last_accessed deltas to the
    store. The candidate list itself is returned unchanged in shape;
    in-place mutation of the candidate dicts reflects the new heat /
    valence values so downstream consumers see consistent state.

    Disabled when ``CORTEX_ABLATE_RECONSOLIDATION=1`` — returns input
    unchanged with zero store writes. The same env var is also honored
    inside `decide_action`; this top-level guard skips the per-candidate
    iteration and store calls entirely when ablated.

    Store contract — uses only methods already on ``PgMemoryStore``:
      - ``bump_heat_raw(memory_id, new_heat_base)`` for the heat delta
      - ``update_memory_access(memory_id)`` for last_accessed + access_count
      - ``update_memory_emotional_valence(memory_id, valence)`` (optional)

    A store stub lacking any of these methods → that mutation is silently
    skipped (test fixtures don't all implement the full A3 surface).
    Failures inside individual store calls are caught per-candidate so
    one bad row never fails the whole recall.

    Source: Nader, Schafe & LeDoux (2000), Nature 406(6797). Bower (1981)
    Am. Psychologist 36(2). Engineering defaults documented in
    `reconsolidation.compute_reconsolidation_action`.
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
                embedding_similarity=None,
                current_directory="",
                context_tokens=q_tokens,
                query_valence=q_valence,
            )
        except Exception as exc:  # noqa: BLE001 — non-load-bearing per-candidate
            silent_failure.note("recall_pipeline.reconsolidation_action", exc)
            continue

        if outcome.action == "none" and outcome.heat_delta == 0.0:
            continue

        # Heat: read current heat_base (best-effort from candidate dict),
        # apply delta, clamp to [0, 1], write through bump_heat_raw.
        if has_bump and outcome.heat_delta != 0.0:
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

        # Optional valence shift (only when the store supports it AND the
        # outcome carries a non-zero shift — Bower 1981 mood-congruent
        # re-storage). Clamped to [-1, +1].
        if has_valence and outcome.valence_delta != 0.0:
            try:
                cur_val = float(c.get("emotional_valence", 0.0) or 0.0)
                new_val = max(-1.0, min(1.0, cur_val + outcome.valence_delta))
                store.update_memory_emotional_valence(c["memory_id"], new_val)
                c["emotional_valence"] = new_val
            except Exception as exc:  # noqa: BLE001
                silent_failure.note("recall_pipeline.valence_writeback", exc)

    return candidates


# ── MOOD_CONGRUENT_RERANK stage ────────────────────────────────────────
# Bower (1981) mood-state-dependent recall: a person in a given mood
# preferentially recalls memories acquired (or stored) in that same mood.
# Distinct from EMOTIONAL_RETRIEVAL — this stage uses a USER session-level
# mood signal, not the per-query valence.


def mood_congruent_rerank(
    candidates: list[dict[str, Any]],
    user_mood: float | None,
    *,
    blend_beta: float = _MOOD_CONGRUENT_BETA,
) -> list[dict[str, Any]]:
    """Rerank by user-mood ↔ candidate-valence congruence.

    ``user_mood`` is a float in [-1, +1] representing the user's current
    affective state (e.g., set by an upstream emotion classifier or a
    manual ``checkpoint`` annotation). When ``None``, the stage no-ops:
    we do NOT fabricate a mood signal in the absence of one.

    Default policy from Bower (1981): mood-congruent — candidates whose
    stored valence is closer to the user's current mood get a rank boost.
    The boost is small (RRF beta=0.15) so the underlying retrieval order
    still dominates; this is a tie-breaker, not a filter.

    Disabled when ``CORTEX_ABLATE_MOOD_CONGRUENT_RERANK=1`` — returns
    input unchanged. Distinct from EMOTIONAL_RETRIEVAL (which uses the
    query text's inferred valence).

    Sources:
      - Bower, G.H. (1981). "Mood and Memory." Am. Psychologist 36(2).
      - Cormack, Clarke & Buettcher (2009). RRF blend.
    """
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


# ── CONFLICT_MONITOR stage (A2 conflict monitoring / cognitive control) ─────────
# Botvinick, Braver, Barch, Carter & Cohen (2001), Psychol. Rev. 108(3):624-652;
# Miller & Cohen (2001), Annu. Rev. Neurosci. 24(1):167-202. The ACC detects
# response conflict — several strong, incompatible responses co-active at once —
# and signals PFC to raise control. Here: a conflict scalar over the retrieved
# set (softmax-entropy of the scores × lexical pairwise contradiction, see
# core.conflict_monitor). When it crosses threshold the set is "in conflict";
# the most-contradictory pair's lower-scoring member is down-weighted and, when
# candidates carry typed-claim metadata, the pair is also routed to the existing
# claim_resolver. Unlike the RRF rerank stages this does not reorder the whole
# list — it demotes one contested-and-weaker memory. Runs after VALUE_PRIORITY
# so it operates on the final content-relevance scores. Behaviour-preserving on
# <2 candidates or low conflict (no-op).


def conflict_monitor_rerank(
    candidates: list[dict[str, Any]],
    store: Any = None,  # noqa: ARG001 — matches the (candidates, store=None) shape shared by sibling rerank stages in this pipeline; this stage is documented pure-planning with no store I/O (see docstring below)
) -> list[dict[str, Any]]:
    """Detect conflict in the retrieved set and demote the losing memory (A2).

    Computes a conflict scalar (``conflict_monitor.assess_conflict``) over the
    candidates. When the set is "in conflict" (score >= threshold): the
    lower-scoring member of the most-contradictory pair is down-weighted and the
    list re-sorted (``conflict_monitor.apply_downweight``), and — when the
    candidates carry the typed-claim metadata the resolver needs — the pair is
    routed to ``claim_resolver.plan_conflicts`` (via
    ``conflict_monitor.route_to_resolver``) so the disagreement is surfaced as
    data. The resulting ConflictPlans are attached to the winning candidate's
    ``conflict_plans`` key for downstream curation; no store write is performed
    here (the resolver is pure planning — persistence is a curation-phase
    concern, matching claim_resolver's design constraint).

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
            # Attach plans + the assessment to the current top candidate so a
            # downstream curation phase can act on them. Non-destructive.
            candidates[0].setdefault("conflict_plans", []).extend(plans)
            candidates[0]["conflict_assessment"] = (
                conflict_monitor.conflict_assessment_as_dict(assessment)
            )
    except Exception:  # noqa: BLE001 — non-load-bearing; never fail a recall
        return candidates

    return candidates
