"""Cross-encoder reranking via FlashRank ONNX.

source: ADR-0242"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.reranker_model import (
    _MODEL_FILE,
    _MODEL_NAME,
    _OFFLINE_ENV,
    RerankerStatus,
    _model_exists,
    _model_path,
    _offline_requested,
    model_sha256,
    reranker_cache_dir,
)
from mcp_server.core.reranker_scoring import (
    _blend_scores,
    _compute_adaptive_alpha,
    _compute_retrieval_confidence,
)
from mcp_server.observability import silent_failure
from mcp_server.shared.telemetry_context import count_reranked

logger = logging.getLogger(__name__)

__all__ = [
    "RerankerStatus",
    "_MODEL_FILE",
    "_MODEL_NAME",
    "_OFFLINE_ENV",
    "_blend_scores",
    "_compute_adaptive_alpha",
    "_compute_retrieval_confidence",
    "_ensure_reranker",
    "_model_path",
    "_offline_requested",
    "ensure_reranker_loaded",
    "get_raw_ce_score",
    "model_sha256",
    "rerank_results",
    "reranker_cache_dir",
    "reranker_status",
]

_flashrank_instance: Any = None
_flashrank_failed: bool = False
_flashrank_load_error: str | None = None


def _ensure_reranker() -> Any:
    """Lazy-load FlashRank ONNX reranker (singleton).

    Precondition: may be called repeatedly within one process; module
    state is process-global and is not thread-safe.
    Postcondition: returns the cached Ranker after successful load, or None
    on failure. Only the first failure logs its cache path and exception.
    reranker_status() exposes the state. Offline mode refuses downloading
    an absent model and follows the same failure path.
    source: ADR-0242"""
    global _flashrank_instance, _flashrank_failed, _flashrank_load_error
    if _flashrank_instance is not None:
        return _flashrank_instance
    if _flashrank_failed:
        return None
    cache = reranker_cache_dir()
    try:
        if _offline_requested() and not _model_exists():
            raise FileNotFoundError(
                f"{_OFFLINE_ENV} is set and the cached model file is absent "
                f"({_model_path()}); refusing to download it, because "
                "FlashRank's fetch has no timeout and would block this "
                "thread indefinitely on a stalled connection"
            )
        from flashrank import Ranker  # noqa: PLC0415 — source: ADR-0242

        _flashrank_instance = Ranker(model_name=_MODEL_NAME, cache_dir=str(cache))
        return _flashrank_instance
    except Exception as exc:  # noqa: BLE001 — source: ADR-0242
        _flashrank_failed = True
        _flashrank_load_error = str(exc)
        logger.warning(
            "FlashRank reranker failed to load (model=%s, cache_dir=%s): %s "
            "-- production re-ranking is DISABLED for the rest of this "
            "process; recall falls back to first-stage WRRF scores only.",
            _MODEL_NAME,
            cache,
            exc,
        )
        return None


def ensure_reranker_loaded() -> RerankerStatus:
    """Force a load attempt now (if not already attempted) and report status.

    source: ADR-0242"""
    _ensure_reranker()
    return reranker_status()


def reranker_status() -> RerankerStatus:
    """Report the FlashRank singleton's current state without triggering a load.

    Precondition: none.
    Postcondition: state == "loaded" iff a prior load succeeded and the
        instance is cached in-process; "failed" iff a prior load raised
        (``error`` carries the exception text); "not_attempted" iff no
        call to ``_ensure_reranker`` / ``ensure_reranker_loaded`` has
        happened yet in this process. Never triggers a load itself.
    """
    model_path = str(_model_path())
    if _flashrank_instance is not None:
        return RerankerStatus(state="loaded", model_path=model_path)
    if _flashrank_failed:
        return RerankerStatus(
            state="failed", model_path=model_path, error=_flashrank_load_error
        )
    return RerankerStatus(state="not_attempted", model_path=model_path)


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
        candidates: (memory_id, wrrf_score) first-stage results.
        content_lookup: memory_id to content map.
        alpha: CE/first-stage blend weight (default 0.70).
        max_content_len: Maximum content length passed to CE.
        adaptive: Adjust alpha using CE score spread (default False).
        apply_platt: If True and fitted parameters exist, calibrate CE scores
            to P(useful|raw_ce) before blending (default False).
    source: ADR-0242"""
    ranker = _ensure_reranker()
    if ranker is None or not candidates:
        return candidates
    try:
        from flashrank import RerankRequest  # noqa: PLC0415 — source: ADR-0242

        passages = [
            {"id": i, "text": content_lookup.get(mid, "")[:max_content_len]}
            for i, (mid, _) in enumerate(candidates)
        ]
        results = ranker.rerank(RerankRequest(query=query, passages=passages))
        count_reranked(len(passages))
        ce_scores = {r["id"]: r["score"] for r in results}
        return _blend_scores(
            candidates, ce_scores, alpha, adaptive=adaptive, apply_platt=apply_platt
        )
    except Exception as exc:  # noqa: BLE001 — source: ADR-0242
        # Distinct failure point from _ensure_reranker's load failure (see
        # reranker_model.py docstring, bb1c581f): the model loaded fine but
        # THIS inference call raised (malformed passage, ONNX runtime error,
        # OOM, ...). Same silent-skip shape, different trigger — must be
        # equally observable.
        silent_failure.note("reranker.rerank_call", exc)
        return candidates


def get_raw_ce_score(
    query: str, content: str, max_content_len: int = 1200
) -> float | None:
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
        from flashrank import RerankRequest  # noqa: PLC0415 — source: ADR-0242

        results = ranker.rerank(
            RerankRequest(
                query=query,
                passages=[{"id": 0, "text": content[:max_content_len]}],
            )
        )
        if not results:
            return None
        return float(results[0].get("score", 0.0))
    except Exception as exc:  # noqa: BLE001 — source: ADR-0242
        silent_failure.note("reranker.raw_ce_score", exc)
        return None
