"""Cross-encoder reranking via FlashRank ONNX.

FlashRank (ms-marco-MiniLM-L-12-v2) provides fast cross-encoder reranking.
Validated through LongMemEval and LoCoMo where it improves MRR by 5-15%.

This module is the FlashRank lifecycle + reranking entrypoint. It owns the
process-global singleton (``_flashrank_instance`` / ``_flashrank_failed`` /
``_flashrank_load_error``) — a lazy-loaded singleton, no persistent I/O,
same shape as write_post_store.py's ``_global_buffer``. Two cohesive
companions carry the rest, and are re-exported here so the public import
surface (``mcp_server.core.reranker.<name>``) is unchanged:

    - ``reranker_model``  — model identity, durable cache_dir, offline
      gate, ``RerankerStatus``, and the on-disk weights sha256. See that
      module's docstring for the 2026-07-11 silent-skip incident (the
      ``/tmp`` cache_dir root cause) and the 2026-07-27 timeout-less
      download hang.
    - ``reranker_scoring`` — the pure score-blending math (confidence
      gate, adaptive alpha, WRRF/CE blend). See that module's docstring
      for the sourced engineering defaults, the rejected Platt sigmoid
      parameters with their benchmark numbers, and the adaptive-alpha
      ablation results.
"""

from __future__ import annotations

import logging
from typing import Any

from mcp_server.core.reranker_model import (
    _MODEL_FILE,
    _MODEL_NAME,
    _OFFLINE_ENV,
    RerankerStatus,
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

    Precondition: none — safe to call unconditionally, any number of
        times, from any thread-unsafe-but-single-process context (module
        state is process-global, matching the existing singleton
        pattern used elsewhere in core — see write_post_store.py).
    Postcondition: returns the cached ``Ranker`` instance once a load has
        succeeded; returns None on any load failure. On the FIRST
        failure only, logs a warning naming the exact cache directory
        searched and the underlying exception — every call thereafter is
        silent (via the ``_flashrank_failed`` flag) to avoid log spam,
        but the state remains introspectable via ``reranker_status()``.
        When ``$CORTEX_RERANKER_OFFLINE`` is set (see
        ``_offline_requested``) and the model file is absent, the
        download is refused and that same failure path is taken —
        bounding what would otherwise be an unbounded network block,
        and degrading to first-stage WRRF scores exactly as a corrupted
        or unreadable cache already does.
    """
    global _flashrank_instance, _flashrank_failed, _flashrank_load_error
    if _flashrank_instance is not None:
        return _flashrank_instance
    if _flashrank_failed:
        return None
    cache = reranker_cache_dir()
    try:
        if _offline_requested() and not _model_path().is_file():
            raise FileNotFoundError(
                f"{_OFFLINE_ENV} is set and the cached model file is absent "
                f"({_model_path()}); refusing to download it, because "
                "FlashRank's fetch has no timeout and would block this "
                "thread indefinitely on a stalled connection"
            )
        from flashrank import Ranker

        _flashrank_instance = Ranker(model_name=_MODEL_NAME, cache_dir=str(cache))
        return _flashrank_instance
    except Exception as exc:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
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

    Public entrypoint for preflight checks — e.g. a benchmark harness
    that must fail fast rather than silently score first-stage-only
    results as if they were production quality (the 2026-07-10 incident
    reranker_model.py's docstring describes). Idempotent: only the first
    call in a process pays the load (or failure) cost.
    """
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
            AF-2 ablation note in reranker_scoring.py's docstring.
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
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("reranker.rerank_call")
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
    except Exception as exc:  # noqa: BLE001 — mechanism boundary — failure is observable via silent_failure ("reranker.raw_ce_score")
        silent_failure.note("reranker.raw_ce_score", exc)
        return None
