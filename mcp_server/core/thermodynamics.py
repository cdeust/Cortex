"""Neuroscience-inspired memory thermodynamics — heat, surprise, decay, importance, valence.

Pure business logic — no I/O. Receives storage/embeddings via constructor injection.
Thermodynamic model with domain-awareness.

Key concepts:
  - Heat: freshness signal (1.0=hot, 0.0=cold). Decays over time, reheated on access.
  - Surprise: novelty signal (1.0=maximally novel). Drives write gate decisions.
  - Importance: heuristic content scoring (errors, decisions, architecture weighted higher).
  - Valence: emotional polarity (-1=frustration, +1=satisfaction). Modulates decay rate.
  - Metamemory: tracks access frequency and usefulness for confidence calibration.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import numpy as np

# ── Keyword sets for heuristic scoring ────────────────────────────────────

_ERROR_KW = re.compile(
    r"\b(error|exception|traceback|failed|failure|bug|crash|broken|timeout|"
    r"denied|rejected|deprecated)\b",
    re.IGNORECASE,
)
_SUCCESS_KW = re.compile(
    r"\b(fixed|resolved|working|success|passed|deployed|completed|shipped|merged|approved)\b",
    re.IGNORECASE,
)
_DECISION_KW = re.compile(
    r"\b(decided|chose|switched|migrated|selected|picked|opted)\b",
    re.IGNORECASE,
)
_ARCHITECTURE_KW = re.compile(
    r"\b(design|pattern|refactor|architecture|restructur|modular|decouple|abstract)\b",
    re.IGNORECASE,
)
_CODE_BLOCK_RE = re.compile(r"```|`[^`]+`")
_FILE_PATH_RE = re.compile(r"(?:\.{0,2}/)?(?:[\w@.-]+/)+[\w@.-]+\.\w+")


def compute_surprise(content: str, existing_similarities: list[float]) -> float:
    """Compute how novel content is relative to existing memories.

    surprise = 1.0 - max_similarity. Returns 0.5 if no existing memories.

    Args:
        content: The content to evaluate.
        existing_similarities: Cosine similarities to existing memories (0.0-1.0).
    """
    if not existing_similarities:
        return 0.5
    max_sim = max(existing_similarities)
    return max(0.0, min(1.0, 1.0 - max_sim))


def apply_surprise_boost(
    base_heat: float, surprise: float, boost_factor: float = 0.3
) -> float:
    """Apply surprise boost to initial heat. Capped at 1.0."""
    return min(base_heat + surprise * boost_factor, 1.0)


def compute_importance(content: str, tags: list[str] | None = None) -> float:
    """Heuristic importance scoring based on content signals. No LLM needed.

    Scores:
      - error/exception keywords: +0.2
      - decision keywords: +0.3
      - architecture keywords: +0.2
      - 3+ tags: +0.1
      - content > 500 chars: +0.1
      - code blocks or file paths: +0.1
    """
    score = 0.0
    if _ERROR_KW.search(content):
        score += 0.2
    if _DECISION_KW.search(content):
        score += 0.3
    if _ARCHITECTURE_KW.search(content):
        score += 0.2
    if tags and len(tags) >= 3:
        score += 0.1
    if len(content) > 500:
        score += 0.1
    if _CODE_BLOCK_RE.search(content) or _FILE_PATH_RE.search(content):
        score += 0.1
    return min(score, 1.0)


def compute_valence(content: str) -> float:
    """Compute emotional valence from content keywords.

    Returns a value in [-1.0, +1.0].
    Negative = frustration (errors), positive = satisfaction (success).
    """
    frustration = len(_ERROR_KW.findall(content))
    satisfaction = len(_SUCCESS_KW.findall(content))
    total = frustration + satisfaction
    if total == 0:
        return 0.0
    return max(-1.0, min(1.0, (satisfaction - frustration) / total))


def compute_decay(
    current_heat: float,
    hours_elapsed: float,
    importance: float = 0.5,
    valence: float = 0.0,
    confidence: float = 1.0,
    *,
    decay_factor: float = 0.95,
    importance_decay_factor: float = 0.998,
    emotional_decay_resistance: float = 0.5,
) -> float:
    """Compute decayed heat using importance, valence, and confidence modifiers.

    Base: heat * (decay_factor ^ hours_elapsed)
    High importance (>0.7): uses slower decay
    High |valence|: resists decay (emotional memories persist)
    High confidence: slight resistance to decay
    """
    if hours_elapsed <= 0:
        return current_heat

    base = importance_decay_factor if importance > 0.7 else decay_factor

    # Emotional resistance pushes factor closer to 1.0
    emotional_mod = 1.0 + abs(valence) * emotional_decay_resistance
    effective = 1.0 - (1.0 - base) / emotional_mod

    # Confidence modifier
    confidence_mod = 1.0 + confidence * 0.1
    effective = 1.0 - (1.0 - effective) / confidence_mod

    effective = max(0.0, min(effective, 1.0))
    return current_heat * (effective**hours_elapsed)


def compute_session_coherence(
    heat: float,
    created_at_iso: str,
    bonus: float = 0.2,
    window_hours: float = 4.0,
) -> float:
    """Boost heat for memories created within the current session window.

    Prevents "I just told you this" by keeping active context elevated.
    """
    try:
        mem_dt = datetime.fromisoformat(created_at_iso)
        if mem_dt.tzinfo is None:
            mem_dt = mem_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        hours = (now - mem_dt).total_seconds() / 3600.0
        if hours < window_hours:
            freshness = 1.0 - (hours / window_hours)
            return min(heat + bonus * freshness, 1.0)
    except (ValueError, TypeError):
        pass
    return heat


def compute_metamemory_confidence(access_count: int, useful_count: int) -> float | None:
    """Update confidence after enough data points. Returns None if not enough data."""
    if access_count <= 3:
        return None
    return useful_count / access_count


def is_error_content(content: str) -> bool:
    """Check if content contains error/exception keywords."""
    return bool(_ERROR_KW.search(content))


def is_decision_content(content: str) -> bool:
    """Check if content contains decision keywords."""
    return bool(_DECISION_KW.search(content))


# ── Test-time learning (Titans, NeurIPS 2025) ─────────────────────────


def compute_retrieval_surprise(
    query_emb: bytes | None, result_embs: list[bytes | None]
) -> float:
    """Surprise = 1 - mean(cosine_sim(query, results)).

    High surprise means results are far from the query embedding —
    the system found unexpected content (Titans: ∇ℓ(M; x) is large).
    Returns 0.5 when embeddings are unavailable.
    """
    if not query_emb or not result_embs:
        return 0.5
    q = np.frombuffer(query_emb, dtype=np.float32)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return 0.5
    sims = []
    for emb in result_embs:
        if emb is None:
            continue
        r = np.frombuffer(emb, dtype=np.float32)
        r_norm = np.linalg.norm(r)
        if r_norm > 0 and len(r) == len(q):
            sims.append(float(np.dot(q, r) / (q_norm * r_norm)))
    if not sims:
        return 0.5
    return max(0.0, min(1.0, 1.0 - sum(sims) / len(sims)))


def compute_heat_adjustment(
    surprise: float,
    momentum: float,
    delta: float = 0.08,
) -> float:
    """Titans-inspired heat delta: Sₜ = η·Sₜ₋₁ - θ·∇ℓ.

    Surprising results (>0.5) get heat boost; unsurprising (<0.3) get suppressed.
    Momentum amplifies the effect when recent recalls were consistently surprising.

    Returns a heat delta in [-delta, +delta].
    """
    amplification = 1.0 + momentum * 0.5
    if surprise > 0.5:
        return delta * (surprise - 0.5) * 2.0 * amplification
    elif surprise < 0.3:
        return -delta * (0.3 - surprise) * amplification
    return 0.0
