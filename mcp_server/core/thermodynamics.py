"""Memory thermodynamics — heat, surprise, decay, importance, valence.

source: ADR-0283"""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timezone

from mcp_server.core import content_cues
from mcp_server.shared.vader import vader_compound
from mcp_server.core.ablation import Mechanism, is_mechanism_disabled
from mcp_server.core.environment import read_environment_variable
from mcp_server.core.value_learning import retention_bonus

# source: ADR-0283


# Resolved lazily on first use (not at module-def time; see
# core/environment.py) and cached forever after, matching the pre-#560
# "read at import" behavior. Fail-fast parsing preserved: a malformed
# value still raises ValueError. source: issue #560
_decay_factor_default_cache: float | None = None


def _decay_factor_default() -> float:
    global _decay_factor_default_cache
    if _decay_factor_default_cache is None:
        override = read_environment_variable("CORTEX_DECAY_LAMBDA")
        _decay_factor_default_cache = float(override) if override else 0.95
    return _decay_factor_default_cache


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


# source: ADR-0283

_MIN_DISTINCT_TERMS = 2


def _edmundson_key(words: list[str]) -> float:
    """Edmundson key feature: TF concentration in top quartile.

    Measures what fraction of total term frequency mass is held by the
    top 25% most frequent terms. Higher concentration = more focused content.
    """
    if not words:
        return 0.0
    freq = Counter(words)
    if len(freq) < _MIN_DISTINCT_TERMS:
        return 0.0
    sorted_counts = sorted(freq.values(), reverse=True)
    total_mass = sum(sorted_counts)
    # Top quartile of unique terms
    top_k = max(1, len(sorted_counts) // 4)
    top_mass = sum(sorted_counts[:top_k])
    return top_mass / total_mass


def compute_importance(content: str, tags: list[str] | None = None) -> float:
    """Edmundson four-feature importance scoring.

    source: ADR-0283

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
    """VADER compound sentiment score.

    source: ADR-0283
    """
    return vader_compound(content)


# source: ADR-0283

# source: ADR-0283
_HIGH_IMPORTANCE = 0.7


def compute_decay(
    current_heat: float,
    hours_elapsed: float,
    importance: float = 0.5,
    valence: float = 0.0,
    confidence: float = 1.0,
    value: float = 0.5,
    *,
    decay_factor: float | None = None,
    importance_decay_factor: float = 0.998,
    emotional_decay_resistance: float = 0.5,
) -> float:
    """Exponential forgetting: heat(t) = heat(0) * λ^t  (Ebbinghaus 1885).

    source: ADR-0283"""
    if decay_factor is None:
        decay_factor = _decay_factor_default()
    if hours_elapsed <= 0:
        return current_heat

    if is_mechanism_disabled(Mechanism.ADAPTIVE_DECAY):
        # No-op: constant lambda (decay_factor), no importance/valence/confidence
        # adaptation; classic Ebbinghaus exponential.
        return current_heat * (decay_factor**hours_elapsed)

    base = importance_decay_factor if importance > _HIGH_IMPORTANCE else decay_factor

    # source: ADR-0283

    time_saturation = 1.0 - math.exp(-hours_elapsed) if hours_elapsed > 0 else 0.0
    emotional_mod = 1.0 + abs(valence) * emotional_decay_resistance * time_saturation
    effective = 1.0 - (1.0 - base) / emotional_mod

    # Confidence modifier
    confidence_mod = 1.0 + confidence * 0.1
    effective = 1.0 - (1.0 - effective) / confidence_mod

    # source: ADR-0283

    value_mod = retention_bonus(value)
    effective = 1.0 - (1.0 - effective) / value_mod

    effective = max(0.0, min(effective, 1.0))
    return current_heat * (effective**hours_elapsed)


def compute_session_coherence(
    heat: float,
    created_at_iso: str,
    bonus: float = 0.2,
    window_hours: float = 4.0,
) -> float:
    """Boost heat for memories created within the current session window.

    source: ADR-0283"""
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


# source: ADR-0283

# source: ADR-0283
_MIN_ACCESSES_FOR_CONFIDENCE = 3


def compute_metamemory_confidence(access_count: int, useful_count: int) -> float | None:
    """Update confidence after enough data points. Returns None if not enough data."""
    if access_count <= _MIN_ACCESSES_FOR_CONFIDENCE:
        return None
    return useful_count / access_count


def is_error_content(content: str) -> bool:
    """Check if content carries an error cue.

    source: ADR-0283

    Delegates to ``content_cues.is_error_cue`` — structural runtime markers
    (tracebacks, stack frames, exception class names, POSIX signals) plus
    multilingual error keywords. See ``content_cues`` for language coverage.
    """
    return content_cues.is_error_cue(content)


def is_decision_content(content: str) -> bool:
    """Check if content carries a decision cue.

    source: ADR-0283
    """
    return content_cues.is_decision_cue(content)
