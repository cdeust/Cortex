"""Query routing and decomposition for multi-signal retrieval.

Routes classified queries to retrieval strategies and decomposes complex
queries into sub-queries for multi-hop retrieval (inspired by IRCoT and
HippoRAG).

Pure business logic — no I/O.
"""

from __future__ import annotations

import re
from typing import Any

from mcp_server.core.query_intent import (
    QueryIntent,
    classify_query_intent,
)


# ── Routing Decisions ─────────────────────────────────────────────────────

_INTENT_TO_HANDLERS: dict[str, list[str]] = {
    QueryIntent.CAUSAL: ["causal_chain_search"],
    QueryIntent.TEMPORAL: ["time_window_search"],
    QueryIntent.ENTITY: ["entity_graph_traversal"],
    QueryIntent.KNOWLEDGE_UPDATE: ["recency_supersession"],
    QueryIntent.MULTI_HOP: ["query_decomposition", "entity_bridging"],
}


def route_query(
    query: str,
    available_signals: list[str] | None = None,
) -> dict[str, Any]:
    """Route a query to the best retrieval strategy.

    Parameters
    ----------
    query: The user's query text.
    available_signals: Which retrieval signals are available
        (e.g., ["vector", "fts", "heat", "causal", "entity"]).

    Returns routing plan with ordered signals and weights.
    """
    classification = classify_query_intent(query)
    weights = classification["weights"]

    if available_signals:
        available_set = set(available_signals)
        weights = {k: v for k, v in weights.items() if k in available_set}

    ordered_signals = sorted(weights.items(), key=lambda x: x[1], reverse=True)
    intent = classification["intent"]
    special_handlers = list(_INTENT_TO_HANDLERS.get(intent, []))

    return {
        "intent": intent,
        "signals": ordered_signals,
        "weights": weights,
        "special_handlers": special_handlers,
        "classification": classification,
    }


# ── Entity Extraction ────────────────────────────────────────────────────

_ENTITY_EXTRACT_RE = re.compile(
    r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b"  # CamelCase
    r"|"
    r"([\w./]+\.\w{1,4})\b"  # File paths
    r"|"
    r"`([^`]+)`"  # Backtick-quoted
)


def extract_query_entities(query: str) -> list[str]:
    """Extract entity references from a query for entity-graph routing."""
    entities: list[str] = []
    for match in _ENTITY_EXTRACT_RE.finditer(query):
        entity = match.group(1) or match.group(2) or match.group(3)
        if entity and len(entity) > 1:
            entities.append(entity)
    return entities


# ── Query Decomposition ──────────────────────────────────────────────────

_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "to",
        "of",
        "and",
        "or",
        "in",
        "on",
        "at",
        "for",
        "with",
        "by",
        "from",
        "it",
        "this",
        "that",
        "i",
        "me",
        "my",
        "do",
        "did",
        "does",
        "what",
        "when",
        "where",
        "why",
        "how",
        "who",
        "which",
        "can",
        "could",
        "would",
        "should",
        "will",
        "about",
        "tell",
    }
)

_TIME_RE = re.compile(
    r"\b(today|yesterday|last\s+\w+|this\s+week|recently|"
    r"\d+\s+(?:hours?|days?|weeks?|months?)\s+ago)\b",
    re.IGNORECASE,
)


def decompose_query(query: str) -> dict[str, Any]:
    """Decompose a query into its constituent parts for multi-signal retrieval.

    Returns:
      - routing: full routing plan
      - entities: extracted entity references
      - keywords: key terms for FTS
      - time_hints: any temporal references
      - sub_queries: generated sub-queries for multi-hop
    """
    routing = route_query(query)
    entities = extract_query_entities(query)

    words = re.findall(r"\b\w+\b", query.lower())
    keywords = [w for w in words if w not in _STOP_WORDS and len(w) > 2]

    time_hints = _TIME_RE.findall(query)
    sub_queries = generate_sub_queries(query, entities, keywords)

    return {
        "routing": routing,
        "entities": entities,
        "keywords": keywords,
        "time_hints": time_hints,
        "sub_queries": sub_queries,
    }


def generate_sub_queries(
    query: str,
    entities: list[str],
    keywords: list[str],
) -> list[str]:
    """Generate sub-queries for multi-hop retrieval.

    For multi-entity queries, creates per-entity sub-queries.
    For complex queries, extracts clause-level sub-queries.

    Inspired by IRCoT (ACL 2023) and HippoRAG (NeurIPS 2024).
    """
    sub_queries: list[str] = []

    # Per-entity sub-queries
    for entity in entities[:4]:
        sub_queries.append(entity)

    # Named entity sub-queries (multi-word proper nouns)
    named = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", query)
    for name in named:
        if name not in sub_queries:
            sub_queries.append(name)

    # Quoted phrase sub-queries
    quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', query)
    for q in quoted:
        phrase = q[0] or q[1]
        if phrase and phrase not in sub_queries:
            sub_queries.append(phrase)

    # Key content-word combinations (2-3 keywords together)
    if len(keywords) >= 3 and not sub_queries:
        sub_queries.append(" ".join(keywords[:3]))

    return sub_queries[:6]
