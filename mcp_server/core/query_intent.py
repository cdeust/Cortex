"""Intent classification and retrieval weight computation.

Detects query intent via regex pattern matching and question-word boosters,
then maps intent to retrieval signal weights for WRRF fusion.

Pure business logic — no I/O.
"""

from __future__ import annotations

import re
from typing import Any


# ── Intent Patterns ───────────────────────────────────────────────────────

_TEMPORAL_RE = re.compile(
    r"\b(when|happened|history|last time|recently|before|after|"
    r"yesterday|today|earlier|previous|chronolog|timeline|sequence)\b",
    re.IGNORECASE,
)

_CAUSAL_RE = re.compile(
    r"\b(why|because|caused|cause|root cause|reason|led to|"
    r"resulted in|consequence|due to|fault|blame|origin|source of)\b",
    re.IGNORECASE,
)

_SEMANTIC_RE = re.compile(
    r"\b(related|similar|like|about|associated|connected|"
    r"relevant|pertaining|regarding|concerning|involves)\b",
    re.IGNORECASE,
)

_ENTITY_RE = re.compile(
    r"\b(what is|who is|tell me about|describe|define|"
    r"explain|details on|info about|information on)\b",
    re.IGNORECASE,
)

_KNOWLEDGE_UPDATE_RE = re.compile(
    r"\b(latest|current|now|recently|updated|changed|new|"
    r"most recent|anymore|still|switched|moved|replaced|"
    r"no longer|instead|currently)\b",
    re.IGNORECASE,
)

_MULTI_HOP_RE = re.compile(
    r"\b(both|and also|as well as|together|between|compare|"
    r"relationship|how does.*relate|connect|in common)\b",
    re.IGNORECASE,
)

# Question words that boost certain intents
_QUESTION_WHY = re.compile(r"^\s*why\b", re.IGNORECASE)
_QUESTION_WHEN = re.compile(r"^\s*when\b", re.IGNORECASE)
_QUESTION_WHAT = re.compile(r"^\s*(what|who)\b", re.IGNORECASE)
_QUESTION_HOW = re.compile(r"^\s*how\b", re.IGNORECASE)


# ── Intent Classification ─────────────────────────────────────────────────


class QueryIntent:
    TEMPORAL = "temporal"
    CAUSAL = "causal"
    SEMANTIC = "semantic"
    ENTITY = "entity"
    KNOWLEDGE_UPDATE = "knowledge_update"
    MULTI_HOP = "multi_hop"
    GENERAL = "general"


def _score_patterns(query: str) -> dict[str, float]:
    """Score each intent via regex pattern matching."""
    scores: dict[str, float] = {
        QueryIntent.TEMPORAL: 0.0,
        QueryIntent.CAUSAL: 0.0,
        QueryIntent.SEMANTIC: 0.0,
        QueryIntent.ENTITY: 0.0,
        QueryIntent.KNOWLEDGE_UPDATE: 0.0,
        QueryIntent.MULTI_HOP: 0.0,
    }

    if _TEMPORAL_RE.search(query):
        scores[QueryIntent.TEMPORAL] += 1.0
    if _CAUSAL_RE.search(query):
        scores[QueryIntent.CAUSAL] += 1.0
    if _SEMANTIC_RE.search(query):
        scores[QueryIntent.SEMANTIC] += 1.0
    if _ENTITY_RE.search(query):
        scores[QueryIntent.ENTITY] += 1.0
    if _KNOWLEDGE_UPDATE_RE.search(query):
        scores[QueryIntent.KNOWLEDGE_UPDATE] += 1.0
        if _ENTITY_RE.search(query):
            scores[QueryIntent.KNOWLEDGE_UPDATE] += 0.5
    if _MULTI_HOP_RE.search(query):
        scores[QueryIntent.MULTI_HOP] += 1.0

    # Multi-entity detection boosts multi-hop
    named_entities = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", query)
    if len(named_entities) >= 2:
        scores[QueryIntent.MULTI_HOP] += 0.5

    return scores


def _apply_question_boosters(query: str, scores: dict[str, float]) -> None:
    """Boost intent scores based on leading question words (in-place)."""
    if _QUESTION_WHY.search(query):
        scores[QueryIntent.CAUSAL] += 0.5
    if _QUESTION_WHEN.search(query):
        scores[QueryIntent.TEMPORAL] += 0.5
    if _QUESTION_WHAT.search(query):
        scores[QueryIntent.ENTITY] += 0.3
        scores[QueryIntent.SEMANTIC] += 0.2
    if _QUESTION_HOW.search(query):
        scores[QueryIntent.CAUSAL] += 0.3


def classify_query_intent(query: str) -> dict[str, Any]:
    """Classify a query's intent for routing.

    Returns:
      - intent: primary intent (temporal/causal/semantic/entity/general)
      - scores: {intent: float} for all intents
      - weights: recommended retrieval weights per signal
    """
    scores = _score_patterns(query)
    _apply_question_boosters(query, scores)

    max_score = max(scores.values())
    if max_score == 0:
        primary = QueryIntent.GENERAL
    else:
        primary = max(scores, key=scores.get)

    weights = compute_retrieval_weights(primary, scores)

    return {
        "intent": primary,
        "scores": {k: round(v, 3) for k, v in scores.items()},
        "weights": weights,
    }


# ── Retrieval Weight Maps ────────────────────────────────────────────────

_BASE_WEIGHTS: dict[str, float] = {
    "vector": 1.0,
    "fts": 0.5,
    "heat": 0.3,
    "temporal": 0.2,
    "causal": 0.1,
    "entity": 0.2,
    "spreading": 0.3,
}

_INTENT_WEIGHT_OVERRIDES: dict[str, dict[str, float]] = {
    QueryIntent.TEMPORAL: {
        "temporal": 1.0,
        "heat": 0.5,
        "vector": 0.5,
        "causal": 0.3,
        "spreading": 0.2,
    },
    QueryIntent.CAUSAL: {
        "causal": 1.0,
        "entity": 0.7,
        "vector": 0.5,
        "temporal": 0.5,
        "spreading": 0.6,
    },
    QueryIntent.SEMANTIC: {
        "vector": 1.0,
        "fts": 0.7,
        "heat": 0.3,
        "entity": 0.5,
        "spreading": 0.5,
    },
    QueryIntent.ENTITY: {
        "entity": 1.0,
        "fts": 0.8,
        "vector": 0.5,
        "causal": 0.3,
        "spreading": 0.8,
    },
    QueryIntent.KNOWLEDGE_UPDATE: {
        "heat": 1.0,
        "vector": 0.8,
        "fts": 0.6,
        "temporal": 0.8,
        "entity": 0.5,
        "spreading": 0.3,
    },
    QueryIntent.MULTI_HOP: {
        "vector": 1.0,
        "fts": 0.7,
        "entity": 0.8,
        "spreading": 1.0,
        "heat": 0.3,
        "causal": 0.5,
    },
}


def compute_retrieval_weights(
    primary_intent: str,
    scores: dict[str, float],
) -> dict[str, float]:
    """Compute retrieval signal weights based on intent.

    Returns weights for: vector, fts, heat, temporal, causal, entity, spreading.
    """
    weights = dict(_BASE_WEIGHTS)
    overrides = _INTENT_WEIGHT_OVERRIDES.get(primary_intent)
    if overrides:
        weights.update(overrides)
    return {k: round(v, 3) for k, v in weights.items()}
