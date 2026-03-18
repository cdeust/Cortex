"""Cross-encoder reranking via FlashRank ONNX.

FlashRank (ms-marco-MiniLM-L-12-v2) provides fast cross-encoder reranking.
Validated through LongMemEval and LoCoMo where it improves MRR by 5-15%.

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


def _blend_scores(
    candidates: list[tuple[int, float]],
    ce_scores: dict[int, float],
    alpha: float,
) -> list[tuple[int, float]]:
    """Blend WRRF scores with cross-encoder scores."""
    reranked = []
    for i, (mem_id, wrrf_score) in enumerate(candidates):
        ce = ce_scores.get(i, 0.0)
        reranked.append((mem_id, (1 - alpha) * wrrf_score + alpha * ce))
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
