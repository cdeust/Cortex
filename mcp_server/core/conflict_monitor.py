"""Conflict monitoring / cognitive control (A2) — a conflict scalar over the
retrieved set that flags when the results disagree.

source: ADR-0134"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any
from mcp_server.core import claim_resolver

# source: ADR-0134


CONFLICT_THRESHOLD: float = 0.35

# source: ADR-0134


LOSER_PENALTY: float = 0.5

# Below this many candidates there is no set to be in conflict over.
_MIN_CANDIDATES: int = 2

# Softmax temperature. 1.0 = use the raw scores; higher flattens the
# distribution (more apparent competition), lower sharpens it.
_SOFTMAX_TEMPERATURE: float = 1.0


# ── Lexical polarity / topic helpers ──────────────────────────────────────────
# Negation / reversal markers. Presence of any of these flips a text's polarity
# sign. This is the "does this item assert the negative of the shared topic"
# signal — lexical, not semantic (see the module honesty note).
_NEGATION_MARKERS: frozenset[str] = frozenset(
    {
        "not",
        "no",
        "never",
        "none",
        "cannot",
        "can't",
        "cant",
        "won't",
        "wont",
        "don't",
        "dont",
        "doesn't",
        "doesnt",
        "isn't",
        "isnt",
        "aren't",
        "arent",
        "wasn't",
        "wasnt",
        "shouldn't",
        "shouldnt",
        "without",
        "avoid",
        "disable",
        "disabled",
        "remove",
        "removed",
        "reverted",
        "revert",
        "reversed",
        "deprecated",
        "abandoned",
        "cancelled",
        "canceled",
        "fails",
        "failed",
        "failing",
        "broken",
        "false",
        "wrong",
        "incorrect",
    }
)

# source: ADR-0134

_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "if",
        "then",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "with",
        "by",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "it",
        "this",
        "that",
        "these",
        "those",
        "as",
        "we",
        "our",
        "you",
        "your",
        "i",
        "they",
        "them",
        "he",
        "she",
        "him",
        "her",
        "do",
        "does",
        "did",
        "so",
        "up",
        "out",
        "now",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9']+")


def _tokens(text: str) -> list[str]:
    """Lower-case word tokens of ``text`` (letters/digits/apostrophes)."""
    return _TOKEN_RE.findall((text or "").lower())


# source: ADR-0134
# source: ADR-0134
_MIN_TOKEN_CHARS = 3


def _topic_tokens(text: str) -> set[str]:
    """Content tokens for topic overlap: tokens minus stopwords and negation
    markers, keeping only tokens of length >= 3 (drops noise like single chars).

    source: ADR-0134"""
    out: set[str] = set()
    for t in _tokens(text):
        if len(t) < _MIN_TOKEN_CHARS:
            continue
        if t in _STOPWORDS or t in _NEGATION_MARKERS:
            continue
        out.add(t)
    return out


def _has_negation(text: str) -> bool:
    """True iff the text carries at least one negation / reversal marker.

    source: ADR-0134"""
    return any(t in _NEGATION_MARKERS for t in _tokens(text))


# ── Scalars ───────────────────────────────────────────────────────────────────
def _softmax(
    scores: list[float], temperature: float = _SOFTMAX_TEMPERATURE
) -> list[float]:
    """Numerically-stable softmax over ``scores`` (shift-by-max), returning a
    probability distribution. Handles negative scores (FlashRank cross-encoder
    outputs can be negative). An empty input returns an empty list.
    """
    if not scores:
        return []
    t = temperature if temperature and temperature > 0 else 1.0
    m = max(scores)
    exps = [math.exp((s - m) / t) for s in scores]
    total = sum(exps)
    if total <= 0.0:
        # All-equal degenerate case — return uniform.
        n = len(scores)
        return [1.0 / n] * n
    return [e / total for e in exps]


def score_entropy(scores: list[float]) -> float:
    """Normalised Shannon entropy of the softmax activation distribution, in
    [0, 1].

    source: ADR-0134"""
    if len(scores) < _MIN_CANDIDATES:
        return 0.0
    probs = _softmax(scores)
    h = 0.0
    for p in probs:
        if p > 0.0:
            h -= p * math.log(p)
    denom = math.log(len(scores))
    if denom <= 0.0:
        return 0.0
    return max(0.0, min(1.0, h / denom))


def pairwise_contradiction(text_a: str, text_b: str) -> float:
    """Lexical contradiction between two texts, in [0, 1].

    ``topic_overlap * polarity_divergence`` where:
      - topic_overlap is the Jaccard similarity of the two content-token sets
        (how much the same thing is being talked about), and
      - polarity_divergence is 1.0 when exactly one of the two texts carries a
        negation / reversal marker (one negates, the other affirms) and 0.0
        when both do or neither does.

    Returns 0.0 when either text has no content tokens or when the polarities
    agree — same-polarity statements about the same topic are corroboration,
    not contradiction. This is lexical only (see the module honesty note): it
    detects surface polarity disagreement about shared words, not semantic
    entailment.
    """
    ta = _topic_tokens(text_a)
    tb = _topic_tokens(text_b)
    if not ta or not tb:
        return 0.0
    if _has_negation(text_a) == _has_negation(text_b):
        return 0.0
    inter = len(ta & tb)
    if inter == 0:
        return 0.0
    union = len(ta | tb)
    jaccard = inter / union if union else 0.0
    return max(0.0, min(1.0, jaccard))


# ── Assessment ────────────────────────────────────────────────────────────────
@dataclass
class ConflictAssessment:
    """The result of one conflict-monitor pass over a candidate set.

    source: ADR-0134"""

    conflict_score: float
    entropy: float
    max_contradiction: float
    competing_pair: tuple[Any, Any] | None
    loser_id: Any | None
    high: bool


def conflict_assessment_as_dict(assessment: "ConflictAssessment") -> dict:
    """Serialize conflict assessment as a dictionary.

    source: ADR-0134
    """
    return {
        "conflict_score": round(assessment.conflict_score, 4),
        "entropy": round(assessment.entropy, 4),
        "max_contradiction": round(assessment.max_contradiction, 4),
        "competing_pair": list(assessment.competing_pair)
        if assessment.competing_pair is not None
        else None,
        "loser_id": assessment.loser_id,
        "high": assessment.high,
    }


def _candidate_text(c: dict[str, Any]) -> str:
    """Best-available text for a candidate — ``content`` then ``text``."""
    return str(c.get("content") or c.get("text") or "")


def assess_conflict(
    candidates: list[dict[str, Any]],
    *,
    threshold: float = CONFLICT_THRESHOLD,
) -> ConflictAssessment:
    """Compute the conflict scalar over a retrieved candidate set.

    Each candidate is a dict with at least a ``score`` and one of
    ``content``/``text``; ``memory_id`` identifies it (falls back to positional
    index). Returns a ``ConflictAssessment``. On fewer than two candidates the
    result is a neutral, low, non-high assessment (nothing to conflict over).

    conflict = max_contradiction * entropy — both a real contradiction and
    genuine co-activation (a flat activation distribution) are required. The
    competing pair is the pair with the highest contradiction; its loser is the
    lower-scoring member.
    """
    n = len(candidates)
    if n < _MIN_CANDIDATES:
        return ConflictAssessment(
            conflict_score=0.0,
            entropy=0.0,
            max_contradiction=0.0,
            competing_pair=None,
            loser_id=None,
            high=False,
        )

    scores = [float(c.get("score", 0.0) or 0.0) for c in candidates]
    entropy = score_entropy(scores)

    # Find the most-contradictory pair. O(n^2) over the retrieved set, which is
    # small (top-k, tens of items) — the same scale the other rerank stages work
    # at.
    best_contra = 0.0
    best_pair_idx: tuple[int, int] | None = None
    texts = [_candidate_text(c) for c in candidates]
    for i in range(n):
        for j in range(i + 1, n):
            contra = pairwise_contradiction(texts[i], texts[j])
            if contra > best_contra:
                best_contra = contra
                best_pair_idx = (i, j)

    conflict_score = max(0.0, min(1.0, best_contra * entropy))
    high = conflict_score >= threshold

    competing_pair: tuple[Any, Any] | None = None
    loser_id: Any | None = None
    if best_pair_idx is not None:
        i, j = best_pair_idx
        a, b = candidates[i], candidates[j]
        aid = a.get("memory_id", i)
        bid = b.get("memory_id", j)
        competing_pair = (aid, bid)
        # Loser = lower score; ties broken by lower heat, then by later index.
        a_score = float(a.get("score", 0.0) or 0.0)
        b_score = float(b.get("score", 0.0) or 0.0)
        if a_score != b_score:
            loser_id = aid if a_score < b_score else bid
        else:
            a_heat = float(a.get("heat", 0.0) or 0.0)
            b_heat = float(b.get("heat", 0.0) or 0.0)
            loser_id = aid if a_heat <= b_heat else bid

    return ConflictAssessment(
        conflict_score=conflict_score,
        entropy=entropy,
        max_contradiction=best_contra,
        competing_pair=competing_pair,
        loser_id=loser_id,
        high=high,
    )


def apply_downweight(
    candidates: list[dict[str, Any]],
    assessment: ConflictAssessment,
    *,
    penalty: float = LOSER_PENALTY,
) -> list[dict[str, Any]]:
    """Down-weight the losing memory of a high-conflict pair, in place, and
    return the re-sorted list.

    source: ADR-0134"""
    if not assessment.high or assessment.loser_id is None:
        return candidates
    factor = 1.0 - max(0.0, min(1.0, penalty))
    for c in candidates:
        if c.get("memory_id") == assessment.loser_id:
            base = float(c.get("score", 0.0) or 0.0)
            c["score"] = base * factor
            c["conflict_downweighted"] = True
            break
    candidates.sort(key=lambda c: c.get("score", 0.0), reverse=True)
    return candidates


def route_to_resolver(candidates: list[dict[str, Any]]) -> list:
    """Route the retrieved set to the existing claim resolver for typed-conflict
    detection, returning ``claim_resolver.ConflictPlan`` objects.

    source: ADR-0134

    Returns an empty list — never raises — when no candidate carries the
    required metadata (the common recall case, where candidates are plain
    memories) or when the resolver finds no typed conflict. The lexical
    contradiction path in ``assess_conflict`` is the fallback that always runs.
    """

    claim_like: list[dict[str, Any]] = []
    for idx, c in enumerate(candidates):
        ctype = c.get("claim_type")
        eids = c.get("entity_ids") or []
        if not ctype or not eids:
            continue
        claim_like.append(
            {
                "id": c.get("memory_id", idx),
                "claim_type": ctype,
                "entity_ids": list(eids),
                "text": _candidate_text(c),
            }
        )
    if len(claim_like) < _MIN_CANDIDATES:
        return []

    prior_by_entity: dict[int, list[dict]] = {}
    for cl in claim_like:
        for eid in cl["entity_ids"]:
            prior_by_entity.setdefault(eid, []).append(cl)

    return claim_resolver.plan_conflicts(claim_like, prior_by_entity)
