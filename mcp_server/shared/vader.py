"""Minimal VADER sentiment analysis for engineering text.

Implements the core algorithm from:
  Hutto CJ & Gilbert E (2014) "VADER: A Parsimonious Rule-based Model for
  Sentiment Analysis of Social Media Text." ICWSM.

Key components implemented:
  - Engineering-domain lexicon (~50 terms with valence ratings [-4, +4])
  - H4: Negation handling (N_SCALAR = -0.74)
  - H3: Degree modifiers (booster words)
  - VADER normalization: compound = x / sqrt(x^2 + alpha), alpha=15

Pure utility — no I/O, no dependencies on core/infrastructure.
"""

from __future__ import annotations

import math
import re

# ── VADER constants (from Hutto & Gilbert 2014) ────────────────────────────

_ALPHA = 15  # normalization constant
_N_SCALAR = -0.74  # negation scalar (H4)

# ── Engineering-domain lexicon: term -> valence [-4, +4] ───────────────────
# Modeled after VADER's crowd-sourced lexicon but tuned for software
# engineering text. Valence magnitudes follow VADER's scale convention.

_LEXICON: dict[str, float] = {
    # Negative [-4, -1]
    "error": -2.0,
    "exception": -2.0,
    "traceback": -2.5,
    "failed": -2.5,
    "failure": -2.5,
    "bug": -2.0,
    "crash": -3.0,
    "broken": -2.5,
    "timeout": -1.5,
    "denied": -1.5,
    "rejected": -1.5,
    "deprecated": -1.0,
    "frustrating": -2.5,
    "annoying": -2.0,
    "painful": -2.0,
    "struggle": -1.5,
    "nightmare": -3.0,
    "horrible": -3.0,
    "terrible": -3.0,
    "awful": -3.0,
    "hate": -3.0,
    "wtf": -3.0,
    "damn": -2.0,
    "ugh": -1.5,
    "argh": -1.5,
    "confusing": -1.5,
    "unclear": -1.0,
    "weird": -1.0,
    "bizarre": -1.5,
    "urgent": -1.5,
    "critical": -1.5,
    "blocking": -2.0,
    "outage": -3.0,
    "hotfix": -1.5,
    # Positive [+1, +4]
    "fixed": 2.0,
    "resolved": 2.0,
    "working": 1.5,
    "success": 2.5,
    "passed": 1.5,
    "deployed": 2.0,
    "completed": 2.0,
    "shipped": 2.5,
    "merged": 1.5,
    "approved": 1.5,
    "elegant": 2.5,
    "beautiful": 2.5,
    "clean": 1.5,
    "perfect": 3.0,
    "excellent": 3.0,
    "awesome": 3.0,
    "great": 2.5,
    "finally": 1.0,
    "breakthrough": 3.0,
    "improvement": 1.5,
    "better": 1.5,
    "love": 2.5,
    "happy": 2.0,
    "proud": 2.0,
    "satisfying": 2.0,
    "insight": 2.0,
    "discovered": 2.0,
    "realized": 1.5,
    "eureka": 3.0,
    "interesting": 1.5,
}

# ── Degree modifiers (H3): word -> scalar multiplier ───────────────────────
# Values from VADER paper Table 3.

_BOOSTERS: dict[str, float] = {
    "very": 0.293,
    "extremely": 0.293,
    "really": 0.293,
    "absolutely": 0.293,
    "incredibly": 0.293,
    "totally": 0.293,
    "completely": 0.293,
    "so": 0.293,
    "slightly": -0.293,
    "somewhat": -0.293,
    "barely": -0.293,
    "hardly": -0.293,
    "kind of": -0.293,
    "sort of": -0.293,
}

# ── Negation words (H4) ───────────────────────────────────────────────────

_NEGATIONS = frozenset({
    "not", "no", "never", "neither", "nobody", "nothing",
    "nowhere", "nor", "cannot", "can't", "couldn't", "shouldn't",
    "wouldn't", "won't", "don't", "doesn't", "didn't", "isn't",
    "aren't", "wasn't", "weren't", "without",
})

_WORD_RE = re.compile(r"[a-z]+(?:'t)?", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    """Extract lowercase word tokens."""
    return [m.group().lower() for m in _WORD_RE.finditer(text)]


def vader_compound(text: str) -> float:
    """Compute VADER compound sentiment score for text.

    Returns a value in [-1.0, +1.0].
    Uses the VADER normalization: compound = x / sqrt(x^2 + alpha).

    Implements:
      - Lexicon lookup
      - H3: Degree modifiers (booster words within 3-token window)
      - H4: Negation handling (N_SCALAR = -0.74 within 3-token window)
    """
    tokens = _tokenize(text)
    if not tokens:
        return 0.0

    sentiments: list[float] = []

    for i, token in enumerate(tokens):
        valence = _LEXICON.get(token, 0.0)
        if valence == 0.0:
            continue

        # H3: Check preceding tokens for degree modifiers (3-word window)
        for j in range(max(0, i - 3), i):
            prev = tokens[j]
            if prev in _BOOSTERS:
                boost = _BOOSTERS[prev]
                # Boost scales with distance: closer = stronger
                dist = i - j
                valence += valence * boost / dist

        # H4: Check preceding tokens for negation (3-word window)
        for j in range(max(0, i - 3), i):
            if tokens[j] in _NEGATIONS:
                valence *= _N_SCALAR
                break  # only apply negation once

        sentiments.append(valence)

    if not sentiments:
        return 0.0

    # VADER normalization
    total = sum(sentiments)
    compound = total / math.sqrt(total * total + _ALPHA)
    return max(-1.0, min(1.0, round(compound, 4)))


def vader_scores(text: str) -> dict[str, float]:
    """Compute VADER pos/neg/neu/compound scores.

    Returns dict with keys: pos, neg, neu, compound.
    pos + neg + neu = 1.0 (proportions of tokens).
    """
    tokens = _tokenize(text)
    compound = vader_compound(text)

    if not tokens:
        return {"pos": 0.0, "neg": 0.0, "neu": 1.0, "compound": 0.0}

    pos_count = 0
    neg_count = 0
    neu_count = 0

    for token in tokens:
        v = _LEXICON.get(token, 0.0)
        if v > 0:
            pos_count += 1
        elif v < 0:
            neg_count += 1
        else:
            neu_count += 1

    total = len(tokens)
    return {
        "pos": round(pos_count / total, 4),
        "neg": round(neg_count / total, 4),
        "neu": round(neu_count / total, 4),
        "compound": compound,
    }
