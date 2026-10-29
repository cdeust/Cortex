"""Scoped hook ranking with explicit inference status and abstention."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Any

from mcp_server.core import reranker, reranker_model
from mcp_server.core.injection_relevance import relevant_by_similarity
from mcp_server.infrastructure.hook_query_encoder import cached_query_scorer
from mcp_server.infrastructure.memory_config import get_memory_settings

logger = logging.getLogger(__name__)

VectorLookup = Callable[[list[int]], dict[int, Any]]


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


def _merge(lexical: list[dict], hot: Iterable[dict]) -> dict[int, dict]:
    rows = {memory["id"]: memory for memory in lexical}
    for memory in hot:
        rows.setdefault(memory["id"], memory)
    return rows


def _eligible(query: str, rows: dict[int, dict], vectors: VectorLookup) -> list[int]:
    """Embedding-similarity admission; raises on encoder or lookup failure."""
    scorer = cached_query_scorer()
    if scorer is None:
        raise RuntimeError("cached query encoder absent")
    stored = {mid: v for mid, v in vectors(list(rows)).items() if mid in rows}
    return relevant_by_similarity(scorer(query, stored))


def rank_memories(
    query: str,
    lexical: list[dict],
    hot_pool: Callable[[], list[dict]],
    vectors: VectorLookup,
) -> list[dict]:
    """Rank eligible rows; inference failure retains protected lexical recall."""
    if not _cached_model_available():
        return _lexical_fallback(lexical, "cached reranker absent")
    try:
        rows = _merge(lexical, hot_pool())
    except Exception as exc:  # noqa: BLE001 -- pool failure preserves lexical recall
        return _lexical_fallback(lexical, f"hot pool unavailable: {exc}")
    if not rows:
        return []
    if reranker.ensure_reranker_loaded().state != "loaded":
        return _lexical_fallback(lexical, "cached reranker failed")
    try:
        similar = _eligible(query, rows, vectors)
    except Exception as exc:  # noqa: BLE001 -- encoder failure preserves lexical recall
        return _lexical_fallback(lexical, f"semantic relevance unavailable: {exc}")
    order = similar + [mid for mid in rows if mid not in set(similar)]
    # source: recall's configured WRRF_K; similarity order is the first stage.
    k = get_memory_settings().WRRF_K
    pairs = [(mid, 1.0 / (k + rank)) for rank, mid in enumerate(order, start=1)]
    ranked = reranker.rerank_for_injection(
        query,
        pairs,
        {mid: memory["content"] for mid, memory in rows.items()},
        frozenset(similar),
    )
    if ranked is None:
        return _lexical_fallback(lexical, "reranking failed")
    return sorted(
        [rows[mid] for mid, _ in ranked], key=lambda memory: not memory["protected"]
    )
