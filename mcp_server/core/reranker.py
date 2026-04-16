"""Cross-encoder reranking via FlashRank ONNX.

FlashRank (ms-marco-MiniLM-L-12-v2) provides fast cross-encoder reranking.
Validated through LongMemEval and LoCoMo where it improves MRR by 5-15%.

CE reranking with alpha blending of first-stage and CE scores is standard
IR practice — linear interpolation of retrieval and CE scores is the common
approach in multi-stage retrieval (Nogueira & Cho, 2019).

Adaptive alpha (EXPERIMENTAL — disabled by default):
    Attempted per-query alpha based on CE score spread (QPP, Shtok et al.,
    TOIS 2012). Hypothesis: high CE spread → CE is confident → boost alpha.
    Results: BEAM -0.002, LME +0.003, LoCoMo -3.8pp MRR / -5.1pp R@10.
    The mechanism cannot distinguish "one great match" from "one outlier".
    Kept as opt-in (adaptive=True) for future experimentation.
    See benchmarks/beam/ablation_results.json for full data.

Sufficient Context gate (Joren et al., ICLR 2025):
    The paper uses an LLM autorater (Gemini 1.5 Pro CoT) to classify whether
    retrieved context is sufficient — not applicable at <200ms retrieval latency.
    This implementation uses a binary threshold gate: if the max CE score
    falls below gate_threshold, all scores are suppressed by a fixed multiplier.

    Platt sigmoid with BENCHMARK-DERIVED A,B — REJECTED (2026-04-03):
    Attempted replacing the binary gate with Platt-calibrated sigmoid
    using hand-picked A, B tuned to max_CE on benchmark data. All benchmarks
    regressed. See reranker_calibration.py for the follow-up: Platt params
    FIT from user rate_memory feedback (different input distribution) are
    applied opt-in via apply_platt=True, default False until benchmark
    re-validation lands.
      A=10, B=-1.5 (inflection 0.15): BEAM 0.479 (-0.148), LoCoMo R@10 92.6% (-5.1pp)
      A=30, B=-1.5 (inflection 0.05): BEAM 0.442 (-0.185)

    ENGINEERING DEFAULTS (not paper-prescribed):
    - alpha=0.70: Base blend weight for CE vs first-stage scores. Empirically
      determined via BEAM ablation (see benchmarks/beam/ablation_results.json):
      0.30→0.511, 0.50→0.529, 0.55→0.535, 0.70→0.542.
    - gate_threshold=0.15: Min CE score to consider retrieval sufficient.
    - suppression=0.1: Score multiplier when gated.

Pure business logic -- lazy-loaded singleton, no persistent I/O.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import platt_calibration, reranker_calibration

_flashrank_instance: Any = None
_flashrank_failed: bool = False


def _ensure_reranker() -> Any:
    """Lazy-load FlashRank ONNX reranker (singleton)."""
    global _flashrank_instance, _flashrank_failed
    if _flashrank_instance is not None:
        return _flashrank_instance
    if _flashrank_failed:
        return None
    try:
        from flashrank import Ranker

        _flashrank_instance = Ranker(model_name="ms-marco-MiniLM-L-12-v2")
        return _flashrank_instance
    except Exception:
        _flashrank_failed = True
        return None


def _compute_retrieval_confidence(
    ce_scores: list[float],
    gate_threshold: float = 0.15,
    suppression: float = 0.1,
) -> float:
    """Compute confidence that retrieval found relevant results.

    Binary threshold gate: if max CE score >= threshold, results are
    considered sufficient (confidence=1.0). Otherwise, all scores are
    suppressed by a fixed multiplier.

    Platt sigmoid was attempted (2026-04-03) and rejected — see module
    docstring for ablation data showing regression on all benchmarks.

    Args:
        ce_scores: Raw cross-encoder scores from FlashRank.
        gate_threshold: Below this max CE, results are likely irrelevant.
            Hand-tuned (0.15 default).
        suppression: Score multiplier when gated. Hand-tuned (0.1 default).

    Returns:
        float — 1.0 (sufficient context) or suppression (insufficient).
    """
    if not ce_scores:
        return suppression
    max_ce = max(ce_scores)
    if max_ce >= gate_threshold:
        return 1.0
    return suppression


def _compute_adaptive_alpha(
    ce_scores: list[float],
    base_alpha: float,
) -> float:
    """Compute per-query alpha from CE score distribution.

    Based on post-retrieval QPP (Shtok et al., TOIS 2012): the standard
    deviation / spread of retrieval scores predicts whether the retrieval
    system can discriminate relevant from non-relevant documents.

    When CE scores have high spread → CE found clear relevance signal →
    trust CE more (higher alpha). When spread is low → ambiguous result
    → use base alpha (already optimized via ablation).

    IMPORTANT: alpha never drops BELOW base_alpha. Ablation on BEAM shows
    lower alpha hurts (0.30→0.511, 0.50→0.529, 0.70→0.542). And higher
    fixed alpha also hurts (0.80→0.476, 0.90→0.469, 1.00→0.465). The
    adaptive mechanism ONLY boosts alpha when CE has high confidence,
    staying at base_alpha otherwise.

    The boost is conservative: base_alpha + small_delta when CE is confident.
    This prevents the regression seen when alpha_min < base_alpha (which
    degraded LME by -3.9pp MRR).

    Args:
        ce_scores: Raw cross-encoder scores from FlashRank.
        base_alpha: Optimized base alpha (0.70 from BEAM ablation).

    Returns:
        Adaptive alpha in [base_alpha, base_alpha + 0.15].
    """
    if len(ce_scores) < 2:
        return base_alpha

    spread = max(ce_scores) - min(ce_scores)
    # Only boost alpha when CE shows high discriminative power.
    # FlashRank scores are typically in [-1, 1], spread ∈ [0, 2].
    # High spread (>0.5) → CE found clear winner → small alpha boost.
    # Low spread → ambiguous → keep base alpha (don't reduce!).
    max_boost = 0.15  # Conservative: max alpha = base + 0.15 = 0.85
    if spread < 0.3:
        return base_alpha
    # Linear boost above spread=0.3, capped at max_boost
    normalized = min((spread - 0.3) / 0.7, 1.0)
    return min(base_alpha + max_boost * normalized, 1.0)


def _blend_scores(
    candidates: list[tuple[int, float]],
    ce_scores: dict[int, float],
    alpha: float,
    adaptive: bool = True,
    apply_platt: bool = False,
) -> list[tuple[int, float]]:
    """Blend WRRF scores with cross-encoder scores, scaled by confidence.

    Retrieval confidence from raw CE scores gates the final blended score.
    When no result strongly matches (low CE), confidence pulls scores down,
    enabling natural abstention for unanswerable queries.

    When adaptive=True, alpha is adjusted per-query based on CE score
    spread (Shtok et al., TOIS 2012 QPP principle).

    When apply_platt=True AND fitted Platt parameters are available from
    user rate_memory feedback, the CE scores used in the blend are
    replaced by their calibrated probabilities P(useful | raw_score)
    via ``platt_calibration.calibrate_score`` (Platt 1999). When no
    parameters exist (cold start) or apply_platt=False, raw CE scores
    are used unchanged — identical to the pre-AF-2 behaviour.
    """
    raw_ce_list = [ce_scores.get(i, 0.0) for i in range(len(candidates))]
    confidence = _compute_retrieval_confidence(raw_ce_list)

    # Per-query adaptive alpha based on CE score distribution
    effective_alpha = _compute_adaptive_alpha(raw_ce_list, alpha) if adaptive else alpha

    # Optional Platt calibration of the CE dimension of the blend. If the
    # calibrator has no fitted params (cold start), calibrate_score is the
    # identity — the blend matches the pre-AF-2 behaviour exactly.
    platt_params = reranker_calibration.get_params() if apply_platt else None

    reranked = []
    for i, (mem_id, wrrf_score) in enumerate(candidates):
        ce = ce_scores.get(i, 0.0)
        ce_for_blend = platt_calibration.calibrate_score(ce, platt_params)
        blended = (1 - effective_alpha) * wrrf_score + effective_alpha * ce_for_blend
        reranked.append((mem_id, blended * confidence))
    reranked.sort(key=lambda x: x[1], reverse=True)
    return reranked


def rerank_results(
    query: str,
    candidates: list[tuple[int, float]],
    content_lookup: dict[int, str],
    alpha: float = 0.70,
    max_content_len: int = 1200,
    adaptive: bool = False,
    apply_platt: bool = False,
) -> list[tuple[int, float]]:
    """Rerank candidates using FlashRank cross-encoder.

    Args:
        query: Search query text.
        candidates: List of (memory_id, wrrf_score) from first-stage retrieval.
        content_lookup: Map of memory_id → content text.
        alpha: Base blend weight for CE vs first-stage (0.70 from BEAM ablation).
        max_content_len: Maximum content length passed to CE.
        adaptive: If True, adjust alpha per-query based on CE score spread
            (Shtok et al., TOIS 2012 QPP principle). Default False pending
            ablation validation.
        apply_platt: If True AND fitted Platt parameters exist in
            reranker_calibration (>=50 rate_memory pairs collected),
            calibrate CE scores to P(useful|raw_ce) before blending.
            Default False until benchmark re-validation lands — see
            AF-2 ablation note in the module docstring.
    """
    ranker = _ensure_reranker()
    if ranker is None or not candidates:
        return candidates
    try:
        from flashrank import RerankRequest

        passages = [
            {"id": i, "text": content_lookup.get(mid, "")[:max_content_len]}
            for i, (mid, _) in enumerate(candidates)
        ]
        results = ranker.rerank(RerankRequest(query=query, passages=passages))
        ce_scores = {r["id"]: r["score"] for r in results}
        return _blend_scores(
            candidates, ce_scores, alpha, adaptive=adaptive, apply_platt=apply_platt
        )
    except Exception:
        return candidates


def get_raw_ce_score(query: str, content: str, max_content_len: int = 1200) -> float | None:
    """Return a single raw FlashRank CE score for (query, content).

    Used by ``rate_memory`` to collect Platt training samples: when the
    caller provides the query that surfaced a memory, we re-encode the
    pair at rating time and record (raw_score, useful) for future fits.

    Returns None if FlashRank is unavailable or encoding fails — the
    caller must handle None (typically: skip the sample).
    """
    ranker = _ensure_reranker()
    if ranker is None or not query or not content:
        return None
    try:
        from flashrank import RerankRequest

        results = ranker.rerank(
            RerankRequest(
                query=query,
                passages=[{"id": 0, "text": content[:max_content_len]}],
            )
        )
        if not results:
            return None
        return float(results[0].get("score", 0.0))
    except Exception:
        return None
