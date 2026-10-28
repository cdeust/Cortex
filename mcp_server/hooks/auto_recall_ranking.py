"""Budgeted hook reranking, reusing recall's FlashRank model and score blend.

Issue #706: an FTS-only top-three cut discards paraphrase candidates before
the cross-encoder can inspect them. Merge a scoped lexical pool with a scoped
hot pool, then use the tool path's reranker. Never download weights in a hook.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from mcp_server.core import reranker, reranker_model
from mcp_server.infrastructure.memory_config import get_memory_settings

logger = logging.getLogger(__name__)


def candidate_limit(limit: int) -> int:
    """Use the configured retrieval pool multiplier (ADR-0534)."""
    return limit * get_memory_settings().WRRF_CANDIDATE_MULTIPLIER


def rank_memories(
    query: str, lexical: list[dict], hot_pool: Callable[[], list[dict]]
) -> list[dict]:
    """Rerank eligible rows; absent cached weights retain lexical behavior.

    Inputs are already project-scoped, current, non-benchmark rows above
    the hook heat floor. The hot pool supplies low-overlap candidates.
    A missing/offline model must not turn heat-only rows into injections.
    """
    try:
        available = reranker_model._model_exists()
    except OSError as exc:
        logger.warning("auto recall reranker cache unavailable: %s", exc)
        available = False
    if not available:
        logger.warning("auto recall degraded: cached reranker absent; lexical only")
        return sorted(lexical, key=lambda m: not m["protected"])
    if reranker.ensure_reranker_loaded().state != "loaded":
        logger.warning("auto recall degraded: cached reranker failed; lexical only")
        return sorted(lexical, key=lambda m: not m["protected"])
    rows = {m["id"]: m for m in lexical}
    try:
        hot = hot_pool()
    except Exception as exc:  # noqa: BLE001 — hook pool boundary retains lexical recall
        logger.warning("auto recall hot pool unavailable: %s", exc)
        hot = []
    for memory in hot:
        rows.setdefault(memory["id"], memory)
    if not rows:
        return []
    # Reciprocal-rank input uses the same WRRF constant as recall (ADR-0221).
    k = get_memory_settings().WRRF_K
    pairs = [(mid, 1.0 / (k + rank)) for rank, mid in enumerate(rows, start=1)]
    ranked = reranker.rerank_results(
        query, pairs, {mid: m["content"] for mid, m in rows.items()}
    )
    if ranked is pairs:
        logger.warning("auto recall degraded: reranking failed; lexical only")
        return sorted(lexical, key=lambda m: not m["protected"])
    return [rows[mid] for mid, _ in ranked]
