"""Intent-adaptive WRRF weight profiles for the PG recall path (#368 split).

Moved verbatim out of ``core/pg_recall.py`` (833 lines against the 500-line
§4.1 limit). Second seam, same rule as the first: WEIGHT POLICY — which
signal matters for which query intent — changes when retrieval is
recalibrated, while the orchestration that consumes it changes when the
pipeline's stages change. Separate reasons to change, separate modules
(§1.1).

Every value here is carried over unchanged; this split re-homed code, it did
not retune anything.
"""

from __future__ import annotations

import os as _os

from mcp_server.core.ablation import Mechanism, is_mechanism_disabled
from mcp_server.core.query_intent import QueryIntent

# ── PG weight profiles ──────────────────────────────────────────────────
# NOTE: These weights are engineering defaults, NOT paper-prescribed values.
# The TMM normalization framework (Bruch et al., ACM TOIS 2023) defines the
# fusion formula but does NOT prescribe per-signal weights — those are
# corpus-specific. See benchmarks/beam/ablation_results.json for empirical
# justification from the BEAM ablation study.

# Ablation data (benchmarks/beam/ablation_results.json):
#   BEAM-optimal: fts=0.0, heat=0.7, ngram=0.0 → MRR 0.554
#   But fts=0.0 regresses LongMemEval -9.2pp R@10, LoCoMo -15.5pp R@10
# These defaults are balanced across all three benchmarks. Per-signal
# BEAM ablation data is recorded but not applied as defaults due to
# cross-benchmark regression. Dynamic corpus adaptation remains an open
# research problem — see Bruch et al. 2023 §5 on collection-dependent weights.
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

    Verification ablation hooks (Popper C2 — operator-disablable mechanism):
    - ``CORTEX_DECAY_DISABLED=1``: forces heat weight to 0.0 so the
      thermodynamic decay signal cannot enter the WRRF fusion. Disabling
      heat is equivalent to "flat heat" for ranking purposes — Cortex
      degenerates to vector + FTS + ngram, the flat-importance baseline.
    - ``CORTEX_HEAT_CONSTANT=<float>``: same effect on the weight (heat
      cannot discriminate when constant), kept as a separate var so the
      n_scan harness can force a specific constant heat at write time and
      confirm the ranker reproduces flat baseline at read time.
    - ``CORTEX_ABLATE_ADAPTIVE_DECAY=1`` (Mechanism.ADAPTIVE_DECAY):
      handler-level read-path guard. Forces heat weight to 0.0 in the
      WRRF fusion so the thermodynamic adaptive-decay signal cannot
      influence ranking. This is the cleaner approach than trying to
      inject ablation into PL/pgSQL — same observable effect at the
      composition root. Source: docs/provenance/verification-protocol.md E1.
    Source: docs/provenance/verification-protocol.md E2 (N-scan); env vars defined
    by benchmarks/lib/n_scan_runner.py:_apply_condition.
    """

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
        _os.environ.get("CORTEX_DECAY_DISABLED") == "1"
        or _os.environ.get("CORTEX_HEAT_CONSTANT")
        or is_mechanism_disabled(Mechanism.ADAPTIVE_DECAY)
    ):
        base["heat"] = 0.0
    return base
