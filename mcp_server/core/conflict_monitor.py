"""Conflict monitoring / cognitive control (A2) — a conflict scalar over the
retrieved set that flags when the results disagree.

A recall can return items that co-activate but contradict each other: one memory
says a decision holds, another reports it was reversed; one says a build passes,
another that it fails. Cortex ranks these purely by relevance, so two mutually-
incompatible memories can sit side by side at the top of the list with nothing
noticing the disagreement. In the brain that situation — several strong,
incompatible responses active at once — is exactly what the anterior cingulate
is thought to detect, signalling prefrontal cortex to raise cognitive control.

Neuroscience basis (DOIs verified against Crossref):
  - Botvinick, Braver, Barch, Carter & Cohen (2001), "Conflict monitoring and
    cognitive control," Psychological Review 108(3):624-652
    (doi:10.1037/0033-295X.108.3.624). The ACC detects *response conflict* — the
    simultaneous activation of incompatible responses — and this conflict signal
    drives an increase in top-down control. Botvinick operationalises conflict
    as Hopfield-style energy over co-active competing units, a scalar computable
    from the units' activations.
  - Miller & Cohen (2001), "An Integrative Theory of Prefrontal Cortex
    Function," Annual Review of Neuroscience 24(1):167-202
    (doi:10.1146/annurev.neuro.24.1.167). Prefrontal cortex represents and
    maintains the control signals that bias processing toward task-appropriate
    responses when conflict is high.

Design (pure business logic — no I/O). Two scalars are computed over the
retrieved set and combined:

  ENTROPY (co-activation) — the retrieval scores are turned into an activation
      distribution via a numerically-stable softmax (the same shift-by-max
      stabilisation hopfield.py uses), and the Shannon entropy of that
      distribution, normalised to [0, 1] by log(n), measures how *distributed*
      activation is. A single dominant winner has low entropy (no competition);
      several near-tied items have high entropy (many co-active competitors).
      This is the tractable proxy for Botvinick's Hopfield energy: energy is
      high only when several mutually-inhibitory units are strongly co-active,
      and a flat activation distribution is the retrieval-side signature of
      exactly that.

  CONTRADICTION — a lexical, pairwise measure of whether two co-active items
      actually *disagree*: shared-topic overlap (Jaccard over content tokens)
      multiplied by polarity divergence (one item carries negation/reversal
      markers about the shared topic and the other does not). High only when two
      items talk about the same thing with opposite polarity.

  CONFLICT SCORE — the product of the two: ``conflict = max_contradiction *
      entropy``. BOTH must be present: a contradiction between co-active
      near-tied competitors scores high (both terms near 1), while a
      contradiction against a clearly dominant winner scores ~0 (entropy ~0 —
      the disagreement is easy to resolve, one item plainly wins), and a healthy
      recall whose top items are all relevant but consistent scores 0 (no
      contradiction). Contradiction is thus necessary and co-activation gates
      it.

When the score crosses a threshold the set is *in conflict*; the competing pair
with the highest contradiction is identified and its lower-scoring member (the
"losing" memory) is down-weighted, and — when the candidates carry the typed
claim metadata the claim resolver needs — the pair is additionally routed to
``claim_resolver.plan_conflicts`` so the disagreement is surfaced as data.

Honesty note (zetetic standard, matching value_learning.py / source_monitoring.py
/ attentional_control.py): this is a heuristic scalar computed over retrieval
scores and candidate text, NOT a trained ACC model and NOT Botvinick's actual
Hopfield-energy network — normalised softmax entropy is a monotone proxy for
that energy, chosen because it is computable directly from the scores the recall
pipeline already produces. Contradiction detection is lexical/polarity-based
(shared tokens + negation markers), NOT semantic entailment: it cannot tell that
"the release shipped" contradicts "we cancelled the launch" without shared
surface tokens, and it will not detect contradictions that hinge on world
knowledge, and it treats polarity as a binary presence-of-negation flag — a
genuine double negation ("not un-shippable") is read as negative, not as a
return to positive. The threshold and the two blend weights are fixed engineering
constants, not parameters fit against a labelled conflict signal. The routing to
``claim_resolver`` reuses the existing typed-claim conflict detector unchanged;
this module adds only the retrieval-time scalar and the down-weight.
"""

from __future__ import annotations

import math
import os as _os
import re
from dataclasses import dataclass
from typing import Any
from mcp_server.core import claim_resolver

# ── Tunable constants (env-overridable, like the recall_pipeline stages) ──────
# A set is "in conflict" when the gated score crosses this threshold. Chosen so
# that a genuine contradiction between two near-tied items (contradiction ~0.5,
# entropy ~1.0 -> conflict ~0.5) fires, while a contradiction against a clearly
# dominant winner (entropy ~0 -> conflict ~0.25) does not.
CONFLICT_THRESHOLD: float = 0.35

# Multiplicative penalty applied to the losing memory's score when a
# high-conflict pair is found. Deliberately partial: the loser is demoted, not
# removed — disagreement is data, and the caller may still want to see both.
LOSER_PENALTY: float = 0.5

# Below this many candidates there is no set to be in conflict over.
_MIN_CANDIDATES: int = 2

# Softmax temperature. 1.0 = use the raw scores; higher flattens the
# distribution (more apparent competition), lower sharpens it.
_SOFTMAX_TEMPERATURE: float = 1.0


def _env_float(name: str, default: float) -> float:
    """Read a float from ``os.environ[name]`` falling back to ``default``.

    Malformed values fall back silently — this is a tuning knob, not a
    load-bearing input, and a bad env var must never fail a recall.
    """
    raw = _os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


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

# Stopwords excluded from topic-overlap. Deliberately does NOT include the
# negation markers above — those carry the polarity signal and must survive.
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


# source: floor documented in the _topic_tokens docstring ("keeping only
# tokens of length >= 3"); tuning provenance not recorded
_MIN_TOKEN_CHARS = 3


def _topic_tokens(text: str) -> set[str]:
    """Content tokens for topic overlap: tokens minus stopwords and negation
    markers, keeping only tokens of length >= 3 (drops noise like single chars).

    Negation markers are stripped here because they measure *polarity*, not
    *topic* — including them would let two negations spuriously overlap.
    """
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

    Presence-based, not parity-based: natural text stacks reinforcing negatives
    ("not complete, it failed") far more often than it genuinely double-negates
    ("not un-shippable"), so counting parity would wrongly cancel the common
    case. The cost is that a true double negation is NOT detected as a return to
    positive polarity — a documented limitation (see the module honesty note),
    not a bug.
    """
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

    0 = one item dominates (no competition); 1 = all items equally active (a
    completely flat distribution). Fewer than two scores return 0.0 — a single
    item cannot compete with itself. The normalisation is by ``log(n)`` (the
    entropy of the uniform distribution over n items) so the value is comparable
    across result-set sizes.
    """
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

    ``conflict_score``    — the gated, entropy-amplified scalar in [0, 1] the
                            threshold is compared against.
    ``entropy``           — normalised softmax entropy of the scores (co-activation).
    ``max_contradiction`` — the highest pairwise contradiction found (0 if none).
    ``competing_pair``    — (memory_id_a, memory_id_b) of the most-contradictory
                            pair, or None when no contradiction was found.
    ``loser_id``          — the memory_id of the lower-scoring member of the
                            competing pair (the one a resolver would down-weight),
                            or None.
    ``high``              — True iff ``conflict_score >= threshold``.
    """

    conflict_score: float
    entropy: float
    max_contradiction: float
    competing_pair: tuple[Any, Any] | None
    loser_id: Any | None
    high: bool

    def as_dict(self) -> dict:
        return {
            "conflict_score": round(self.conflict_score, 4),
            "entropy": round(self.entropy, 4),
            "max_contradiction": round(self.max_contradiction, 4),
            "competing_pair": list(self.competing_pair)
            if self.competing_pair is not None
            else None,
            "loser_id": self.loser_id,
            "high": self.high,
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

    No-op (returns the input unchanged) when the assessment is not ``high`` or
    carries no ``loser_id``. When it fires, the loser's ``score`` is multiplied
    by ``(1 - penalty)`` and the list is re-sorted by score descending, so the
    contested-and-weaker memory drops below its corroborated rivals. The winner
    is left untouched — this demotes the loser rather than boosting the winner,
    keeping the operation conservative.
    """
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

    This reuses ``claim_resolver.plan_conflicts`` unchanged. It is only
    meaningful when the candidates carry the typed-claim metadata that detector
    needs — ``claim_type`` and ``entity_ids``. The retrieved set is treated as a
    self-contained batch: each candidate is also registered as a potential prior
    for every entity it mentions, so ``plan_conflicts`` can surface
    disagreeing-type pairs (e.g. a decision paired with a limitation) about
    shared entities.

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
