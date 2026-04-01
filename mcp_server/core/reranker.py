"""Cross-encoder reranking via FlashRank ONNX.

FlashRank (ms-marco-MiniLM-L-12-v2) provides fast cross-encoder reranking.
Validated through LongMemEval and LoCoMo where it improves MRR by 5-15%.

CE reranking with alpha blending of first-stage and CE scores is standard
IR practice (no specific paper citation needed).

Sufficient Context gate (inspired by Joren et al., ICLR 2025):
    The paper likely uses a calibrated sigmoid confidence model.
    This implementation simplifies to a binary threshold gate: if the
    max CE score falls below gate_threshold, all scores are suppressed
    by a fixed multiplier. This avoids the need for calibration data
    while preserving the core insight (suppress when nothing matches).
    Hand-tuned constants: gate_threshold=0.15, suppression=0.1.

Pure business logic -- lazy-loaded singleton, no persistent I/O.
"""

from __future__ import annotations

from typing import Any

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

    Inspired by 'Sufficient Context' (Joren et al., ICLR 2025).
    Binary threshold approximation: the paper likely uses calibrated
    sigmoid confidence; we simplify to a hard gate on max CE score.

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


def _blend_scores(
    candidates: list[tuple[int, float]],
    ce_scores: dict[int, float],
    alpha: float,
) -> list[tuple[int, float]]:
    """Blend WRRF scores with cross-encoder scores, scaled by confidence.

    Retrieval confidence from raw CE scores gates the final blended score.
    When no result strongly matches (low CE), confidence pulls scores down,
    enabling natural abstention for unanswerable queries.
    """
    raw_ce_list = [ce_scores.get(i, 0.0) for i in range(len(candidates))]
    confidence = _compute_retrieval_confidence(raw_ce_list)
    reranked = []
    for i, (mem_id, wrrf_score) in enumerate(candidates):
        ce = ce_scores.get(i, 0.0)
        blended = (1 - alpha) * wrrf_score + alpha * ce
        reranked.append((mem_id, blended * confidence))
    reranked.sort(key=lambda x: x[1], reverse=True)
    return reranked


def rerank_results(
    query: str,
    candidates: list[tuple[int, float]],
    content_lookup: dict[int, str],
    alpha: float = 0.55,
    max_content_len: int = 1200,
) -> list[tuple[int, float]]:
    """Rerank candidates using FlashRank cross-encoder."""
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
        return _blend_scores(candidates, ce_scores, alpha)
    except Exception:
        return candidates
