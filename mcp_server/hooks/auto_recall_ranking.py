"""Scoped hook reranking with explicit inference status and abstention."""

from __future__ import annotations

import logging
from collections.abc import Callable

from mcp_server.core import reranker, reranker_model
from mcp_server.infrastructure.memory_config import get_memory_settings

logger = logging.getLogger(__name__)


def candidate_limit(limit: int) -> int:
    """Use the configured retrieval pool multiplier from MemorySettings."""
    return limit * get_memory_settings().WRRF_CANDIDATE_MULTIPLIER


def _lexical_fallback(lexical: list[dict], reason: str) -> list[dict]:
    """Keep protected-first lexical behavior with an observable degradation."""
    logger.warning("auto recall degraded: %s; lexical only", reason)
    return sorted(lexical, key=lambda memory: not memory["protected"])


def _cached_model_available() -> bool:
    """Probe disk cache without downloading; an unwired cache is unavailable."""
    try:
        return reranker_model._model_exists()
    except (OSError, RuntimeError) as exc:
        logger.warning("auto recall reranker cache unavailable: %s", exc)
        return False


def rank_memories(
    query: str, lexical: list[dict], hot_pool: Callable[[], list[dict]]
) -> list[dict]:
    """Rank eligible rows; inference failure retains protected lexical recall."""
    if not _cached_model_available():
        return _lexical_fallback(lexical, "cached reranker absent")
    rows = {memory["id"]: memory for memory in lexical}
    try:
        hot = hot_pool()
    except Exception as exc:  # noqa: BLE001 -- pool failure preserves lexical recall
        return _lexical_fallback(lexical, f"hot pool unavailable: {exc}")
    for memory in hot:
        rows.setdefault(memory["id"], memory)
    if not rows:
        return []
    if reranker.ensure_reranker_loaded().state != "loaded":
        return _lexical_fallback(lexical, "cached reranker failed")
    # source: recall's configured WRRF_K; preserve reciprocal-rank input.
    k = get_memory_settings().WRRF_K
    pairs = [(mid, 1.0 / (k + rank)) for rank, mid in enumerate(rows, start=1)]
    ranked = reranker.rerank_for_injection(
        query, pairs, {mid: memory["content"] for mid, memory in rows.items()}
    )
    if ranked is None:
        return _lexical_fallback(lexical, "reranking failed")
    return sorted(
        [rows[mid] for mid, _ in ranked], key=lambda memory: not memory["protected"]
    )
