"""Memory thermodynamics — heat, surprise, decay, importance, valence.

Pure business logic — no I/O.

Key concepts:
  - Heat: freshness signal (1.0=hot, 0.0=cold). Decays over time, reheated on access.
  - Surprise: novelty signal (1.0=maximally novel). Drives write gate decisions.
  - Importance: Edmundson (1969) four-feature scoring (cue + key + title + loc).
  - Valence: VADER compound sentiment (Hutto & Gilbert 2014).
  - Metamemory: tracks access frequency and usefulness for confidence calibration.

Citations:
  - compute_decay: Exponential forgetting curve (Ebbinghaus, 1885,
    "Über das Gedächtnis"). R(t) = e^{-t/S} where S is memory stability.
    Importance and valence modulate S, following the finding that emotional
    and meaningful memories decay slower (McGaugh 2004, "The amygdala
    modulates the consolidation of memories of emotionally arousing
    experiences", Annual Review of Neuroscience).
  - compute_surprise: Simple cosine distance novelty. No paper claimed.
  - compute_importance: Edmundson HP (1969) "New Methods in Automatic
    Extracting." JACM 16(2):264-285. Four-feature scoring with validated
    weights: w_cue=2, w_key=1, w_title=1, w_loc=1.
  - compute_valence: Hutto CJ & Gilbert E (2014) "VADER: A Parsimonious
    Rule-based Model for Sentiment Analysis of Social Media Text." ICWSM.
    compound = x / sqrt(x^2 + alpha), alpha=15.
  - compute_session_coherence: Linear recency bonus. No paper — engineering
    decision to prevent "I just told you this" failures.
  - compute_metamemory_confidence: Frequentist accuracy (useful/total).
    Loosely inspired by Nelson & Narens (1990) metamemory framework but
    implemented as a simple ratio, not their full monitoring-control model.
"""

from __future__ import annotations

import math

import re
from collections import Counter
from datetime import datetime, timezone

from mcp_server.shared.vader import vader_compound

# ── Edmundson cue word sets ───────────────────────────────────────────────
# Bonus words: domain-specific high-importance indicators (positive cue)
# Stigma words: low-importance indicators (negative cue)

_BONUS_WORDS = frozenset(
    {
        "error",
        "exception",
        "traceback",
        "failed",
        "failure",
        "bug",
        "crash",
        "broken",
        "timeout",
        "denied",
        "rejected",
        "deprecated",
        "decided",
        "chose",
        "switched",
        "migrated",
        "selected",
        "picked",
        "opted",
        "design",
        "pattern",
        "refactor",
        "architecture",
        "restructure",
        "modular",
        "decouple",
        "abstract",
        "breaking",
        "migration",
        "critical",
        "security",
        "vulnerability",
        "performance",
        "bottleneck",
        "regression",
        "root cause",
    }
)

_STIGMA_WORDS = frozenset(
    {
        "maybe",
        "minor",
        "trivial",
        "fyi",
        "note",
        "aside",
        "btw",
        "probably",
        "might",
        "perhaps",
        "just",
        "small",
    }
)

_CODE_BLOCK_RE = re.compile(r"```|`[^`]+`")
_FILE_PATH_RE = re.compile(r"(?:\.{0,2}/)?(?:[\w@.-]+/)+[\w@.-]+\.\w+")
_WORD_RE = re.compile(r"[a-z]+(?:'[a-z]+)?", re.IGNORECASE)

# ── Keyword patterns for backward-compatible helper functions ─────────────

_ERROR_KW = re.compile(
    r"\b(error|exception|traceback|failed|failure|bug|crash|broken|timeout|"
    r"denied|rejected|deprecated)\b",
    re.IGNORECASE,
)
_DECISION_KW = re.compile(
    r"\b(decided|chose|switched|migrated|selected|picked|opted)\b",
    re.IGNORECASE,
)


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


def _edmundson_cue(words: list[str]) -> float:
    """Edmundson cue feature: bonus/stigma word ratio.

    cue(m) = (bonus_count - stigma_count) / content_words, clamped [0, 1].
    Code blocks and file paths count as bonus indicators for technical content.
    """
    if not words:
        return 0.0
    bonus = sum(1 for w in words if w in _BONUS_WORDS)
    stigma = sum(1 for w in words if w in _STIGMA_WORDS)
    raw = (bonus - stigma) / len(words)
    return max(0.0, min(1.0, raw))


def _edmundson_key(words: list[str]) -> float:
    """Edmundson key feature: TF concentration in top quartile.

    Measures what fraction of total term frequency mass is held by the
    top 25% most frequent terms. Higher concentration = more focused content.
    """
    if not words:
        return 0.0
    freq = Counter(words)
    if len(freq) < 2:
        return 0.0
    sorted_counts = sorted(freq.values(), reverse=True)
    total_mass = sum(sorted_counts)
    # Top quartile of unique terms
    top_k = max(1, len(sorted_counts) // 4)
    top_mass = sum(sorted_counts[:top_k])
    return top_mass / total_mass


def compute_importance(content: str, tags: list[str] | None = None) -> float:
    """Edmundson (1969) four-feature importance scoring.

    Edmundson HP (1969) "New Methods in Automatic Extracting."
    JACM 16(2):264-285.

    importance = w_cue * cue(m) + w_key * key(m) + w_title * title(m)
                 + w_loc * loc(m)

    Validated weights: w_cue=2, w_key=1, w_title=1, w_loc=1.

    For single-unit memories (no document structure):
      - title(m): tags as proxy (tag overlap with bonus words), else 0
      - loc(m): 0 (no positional signal for atomic memories)
      - Code blocks and file paths add to cue score (technical content cue)

    Final score normalized to [0, 1].
    """
    words = [m.group().lower() for m in _WORD_RE.finditer(content)]

    # cue(m): bonus/stigma word ratio + technical content indicators
    cue = _edmundson_cue(words)
    # Boost cue for code blocks and file paths (technical cue signals)
    if _CODE_BLOCK_RE.search(content) or _FILE_PATH_RE.search(content):
        cue = min(1.0, cue + 0.15)

    # key(m): TF concentration
    key = _edmundson_key(words)

    # title(m): tags as proxy — fraction of tags that are bonus words
    title = 0.0
    if tags:
        tag_words = {t.lower() for t in tags}
        overlap = tag_words & _BONUS_WORDS
        title = len(overlap) / len(tags) if tags else 0.0

    # loc(m): not applicable for single-unit memories
    loc = 0.0

    # Edmundson validated weights
    w_cue, w_key, w_title, w_loc = 2, 1, 1, 1
    raw = w_cue * cue + w_key * key + w_title * title + w_loc * loc

    # Normalize: max possible raw = 2*1 + 1*1 + 1*1 + 1*0 = 4
    # But typical scores are much lower; normalize to [0, 1]
    max_raw = w_cue + w_key + w_title + w_loc  # 5
    return min(1.0, round(raw / max_raw, 4))


def compute_valence(content: str) -> float:
    """VADER compound sentiment score (Hutto & Gilbert 2014).

    Returns a value in [-1.0, +1.0].
    Uses engineering-domain lexicon with negation and degree modifiers.
    compound = x / sqrt(x^2 + alpha), alpha=15.
    """
    return vader_compound(content)


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
    """Exponential forgetting: heat(t) = heat(0) * λ^t  (Ebbinghaus 1885).

    λ (effective decay factor per hour) is modulated by:
      - Importance > 0.7: λ increases to importance_decay_factor (slower decay).
        Rationale: meaningful memories consolidate better (Craik & Lockhart 1972,
        levels-of-processing).
      - |valence|: pushes λ toward 1.0 (emotional memories resist decay).
        Rationale: amygdala modulation of consolidation (McGaugh 2004).
      - confidence: minor λ increase. Engineering decision — no paper.

    Constants: decay_factor=0.95 and importance_decay_factor=0.998 are tuned
    to produce reasonable half-lives (~14h normal, ~346h important) for a
    memory system operating at hours/days timescale. Not from any paper.
    """
    if hours_elapsed <= 0:
        return current_heat

    base = importance_decay_factor if importance > 0.7 else decay_factor

    # Emotional resistance: time-dependent (Yonelinas & Ritchey 2015).
    # Emotional advantage grows with delay (Kleinsmith & Kaplan 1963 crossover).
    # At t=0: no resistance. At t>>1h: full resistance (up to 30% at |v|=1).
    time_saturation = 1.0 - math.exp(-hours_elapsed) if hours_elapsed > 0 else 0.0
    emotional_mod = 1.0 + abs(valence) * emotional_decay_resistance * time_saturation
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
