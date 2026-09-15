"""Intent-adaptive WRRF weight profiles for the PG recall path.

source: ADR-0221
"""

from __future__ import annotations

from mcp_server.core.ablation import Mechanism, is_mechanism_disabled
from mcp_server.core.environment import read_environment_variable
from mcp_server.core.query_intent import QueryIntent

# source: ADR-0221


# source: ADR-0221


_BASE_PG_WEIGHTS: dict[str, float] = {
    "vector": 1.0,  # Primary signal — always full strength
    "fts": 0.5,  # Keyword matching: essential for factual/technical queries
    "heat": 0.3,  # Thermodynamic importance signal
    "ngram": 0.3,  # Fuzzy matching: helps partial/code token matches
    "recency": 0.0,  # Disabled by default; enabled for temporal intents
}

_PG_INTENT_OVERRIDES: dict[str, dict[str, float]] = {
    QueryIntent.TEMPORAL: {
        "heat": 0.6,
        "recency": 0.2,
    },
    QueryIntent.KNOWLEDGE_UPDATE: {
        "recency": 0.5,
        "heat": 0.5,
    },
    QueryIntent.EVENT_ORDER: {
        "heat": 0.4,
        "recency": 0.3,
        "fts": 0.6,
    },
    QueryIntent.SUMMARIZATION: {
        "heat": 0.5,
        "fts": 0.7,
    },
    QueryIntent.PREFERENCE: {
        "fts": 0.8,
        "heat": 0.5,
    },
}


def compute_pg_weights(
    intent: str, core_weights: dict | None = None
) -> dict[str, float]:
    """Compute PG recall_memories() signal weights for a given intent.

    Derives base weights from core_weights (from query_intent) when available,
    then applies intent-specific PG overrides.

    source: ADR-0221"""

    cw = core_weights or {}
    # Vector is always 1.0 in the PG path — it's the primary discovery signal.
    # Other signals derived from core_weights (intent system) when available,
    # falling back to _BASE_PG_WEIGHTS defaults.
    base = {
        "vector": 1.0,
        "fts": cw.get("fts", _BASE_PG_WEIGHTS["fts"]),
        "heat": cw.get("heat", _BASE_PG_WEIGHTS["heat"]),
        "ngram": cw.get("fts", _BASE_PG_WEIGHTS["fts"]) * 0.6,
        "recency": 0.0,
    }
    overrides = _PG_INTENT_OVERRIDES.get(intent)
    if overrides:
        base.update(overrides)
    if (
        read_environment_variable("CORTEX_DECAY_DISABLED") == "1"
        or read_environment_variable("CORTEX_HEAT_CONSTANT")
        or is_mechanism_disabled(Mechanism.ADAPTIVE_DECAY)
    ):
        base["heat"] = 0.0
    return base
