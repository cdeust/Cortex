"""3-tier retrieval dispatch: simple, mixed (multi-hop), deep (BM25-primary).

Dispatch strategy (validated via LoCoMo, LongMemEval, BEAM benchmarks):
  - Simple: balanced 9-signal WRRF (general/semantic/temporal)
  - Mixed: multi-hop with entity bridging (multi-hop intent)
  - Deep: BM25-primary + entity-weighted (entity/factual queries)

Pure business logic -- no I/O. Takes signals as data.
"""

from __future__ import annotations

from typing import Any, Callable

from mcp_server.core.query_decomposition import decompose_query
from mcp_server.core.query_intent import QueryIntent
from mcp_server.core.reranker import rerank_results

# ── Tier Classification ──────────────────────────────────────────────────

SIMPLE_INTENTS = {
    QueryIntent.GENERAL,
    QueryIntent.SEMANTIC,
    QueryIntent.TEMPORAL,
    QueryIntent.CAUSAL,
    QueryIntent.KNOWLEDGE_UPDATE,
}
MIXED_INTENTS = {QueryIntent.MULTI_HOP}
DEEP_INTENTS = {QueryIntent.ENTITY, QueryIntent.INSTRUCTION}


def classify_tier(intent: str) -> str:
    """Map query intent to retrieval tier."""
    if intent in MIXED_INTENTS:
        return "mixed"
    if intent in DEEP_INTENTS:
        return "deep"
    return "simple"


# ── WRRF Fusion ──────────────────────────────────────────────────────────


def wrrf_fuse(
    signal_results: list[list[tuple[int, float]]],
    signal_weights: list[float],
    k: int = 60,
) -> list[tuple[int, float]]:
    """Weighted Reciprocal Rank Fusion across multiple signals."""
    scores: dict[int, float] = {}
    for results, weight in zip(signal_results, signal_weights):
        if weight <= 0:
            continue
        for rank, (mem_id, _) in enumerate(results):
            scores[mem_id] = scores.get(mem_id, 0.0) + weight / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# ── Signal Weights ───────────────────────────────────────────────────────

_SIGNAL_NAMES = [
    "vector",
    "fts",
    "heat",
    "hopfield",
    "hdc",
    "sr",
    "sa",
    "bm25",
    "ngram",
]


def _base_weights(v: float, f: float, h: float, sa: float) -> dict[str, float]:
    """Default balanced weights."""
    return {
        "vector": v,
        "fts": f,
        "heat": h,
        "hopfield": v * 0.5,
        "hdc": v * 0.4,
        "sr": h * 0.6,
        "sa": sa,
        "bm25": f * 0.8,
        "ngram": f * 0.6,
    }


def _deep_weights(v: float, f: float, h: float, sa: float) -> dict[str, float]:
    """BM25-primary weights for entity/factual queries."""
    return {
        "vector": v * 0.7,
        "fts": f * 1.2,
        "heat": h * 0.5,
        "hopfield": v * 0.3,
        "hdc": v * 0.2,
        "sr": h * 0.3,
        "sa": sa * 1.5,
        "bm25": f * 1.5,
        "ngram": f * 1.0,
    }


def _mixed_weights(v: float, f: float, h: float, sa: float) -> dict[str, float]:
    """Balanced weights for multi-hop queries."""
    return {
        "vector": v,
        "fts": f,
        "heat": h,
        "hopfield": v * 0.5,
        "hdc": v * 0.4,
        "sr": h * 0.6,
        "sa": sa * 1.2,
        "bm25": f * 0.8,
        "ngram": f * 0.6,
    }


def _instruction_weights(v: float, f: float, h: float, sa: float) -> dict[str, float]:
    """BM25+FTS-primary weights for instruction/directive queries.

    Instructions have distinctive lexical patterns ("always", "never", "must").
    BM25 IDF weighting surfaces rare directive keywords that vector similarity
    misses. Reduced vector weight avoids dilution by topic-adjacent content.
    """
    return {
        "vector": v * 0.5,
        "fts": f * 1.5,
        "heat": h * 0.5,
        "hopfield": v * 0.2,
        "hdc": v * 0.2,
        "sr": h * 0.3,
        "sa": sa * 0.5,
        "bm25": f * 2.0,
        "ngram": f * 1.2,
    }


def compute_signal_weights(
    tier: str,
    intent_weights: dict[str, float],
    base_vector: float = 1.0,
    base_fts: float = 0.5,
    base_heat: float = 0.3,
    intent: str | None = None,
) -> dict[str, float]:
    """Compute per-signal WRRF weights based on tier and intent."""
    v = base_vector * intent_weights.get("vector", 1.0)
    f = base_fts * intent_weights.get("fts", 1.0)
    h = base_heat * intent_weights.get("heat", 1.0)
    sa = f * 0.5 * intent_weights.get("spreading", 1.0)
    if intent == QueryIntent.INSTRUCTION:
        return _instruction_weights(v, f, h, sa)
    if tier == "deep":
        return _deep_weights(v, f, h, sa)
    if tier == "mixed":
        return _mixed_weights(v, f, h, sa)
    return _base_weights(v, f, h, sa)


# ── Multi-Hop Merge ─────────────────────────────────────────────────────


def merge_multihop_results(
    primary: list[tuple[int, float]],
    secondary: list[tuple[int, float]],
    hop_weight: float = 0.3,
) -> list[tuple[int, float]]:
    """Merge hop results: reinforce existing, add new at reduced weight."""
    scores = {mid: score for mid, score in primary}
    for mid, score in secondary:
        if mid in scores:
            scores[mid] += score * hop_weight
        else:
            scores[mid] = score * hop_weight
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def _run_multihop(
    query: str,
    fused: list[tuple[int, float]],
    hop_fn: Callable[[str], list[tuple[int, float]]],
) -> list[tuple[int, float]]:
    """Execute multi-hop sub-queries and merge into fused results."""
    decomposition = decompose_query(query)
    for sub_q in decomposition.get("sub_queries", [])[:3]:
        hop_results = hop_fn(sub_q)
        if hop_results:
            fused = merge_multihop_results(fused, hop_results)
    return fused


# ── Orchestrator ─────────────────────────────────────────────────────────


def dispatch_retrieval(
    query: str,
    signals: dict[str, list[tuple[int, float]]],
    intent_info: dict[str, Any],
    content_lookup: dict[int, str],
    wrrf_k: int = 60,
    base_vector_w: float = 1.0,
    base_fts_w: float = 0.5,
    base_heat_w: float = 0.3,
    max_results: int = 10,
    hop_fn: Callable[[str], list[tuple[int, float]]] | None = None,
) -> tuple[list[tuple[int, float]], str]:
    """Run 3-tier retrieval dispatch. Returns (results, tier_name)."""
    intent = intent_info.get("intent", QueryIntent.GENERAL)
    tier = classify_tier(intent)
    weights = compute_signal_weights(
        tier,
        intent_info.get("weights", {}),
        base_vector_w,
        base_fts_w,
        base_heat_w,
        intent=intent,
    )
    signal_lists = [signals.get(n, []) for n in _SIGNAL_NAMES]
    weight_list = [weights.get(n, 0.0) for n in _SIGNAL_NAMES]
    fused = wrrf_fuse(signal_lists, weight_list, k=wrrf_k)

    if tier == "mixed" and hop_fn is not None:
        try:
            fused = _run_multihop(query, fused, hop_fn)
        except Exception:
            pass

    rerank_pool = fused[: max_results * 3]
    if content_lookup:
        try:
            rerank_pool = rerank_results(query, rerank_pool, content_lookup)
        except Exception:
            pass
    return rerank_pool, tier
