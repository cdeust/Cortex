"""Recollection vs. familiarity — dual-process retrieval (C2).

Human memory retrieval is not one process but two. *Familiarity* is a fast,
a-contextual sense that an item has been encountered before — a scalar signal
of prior exposure available almost immediately, with no recovery of the item's
associated context. *Recollection* is a slower, contextual reconstruction that
brings back the specifics — where and when the item was encountered and what
accompanied it. The two dissociate behaviourally and anatomically: familiarity
is associated with perirhinal cortex, recollection with the hippocampus.

Cortex already has the *shape* of this dissociation in its retrieve→rerank
pipeline. A cheap first-pass fusion (``recall_memories`` WRRF) surfaces
candidates; an expensive post-WRRF chain (Hopfield completion, HDC, spreading
activation, dendritic modulation, emotional/mood reranking, reconsolidation,
FlashRank, value/conflict) reconstructs the contextual ordering. What was
missing is the *early gate*: a lightweight a-contextual familiarity signal read
BEFORE the expensive chain, so an overwhelmingly-familiar query can be answered
without paying for full reconstruction (two-stage retrieval — cheap recall +
expensive rerank — is standard IR practice).

Neuroscience basis (DOIs verified against Crossref):
  - Yonelinas (2002), "The Nature of Recollection and Familiarity: A Review of
    30 Years of Research," Journal of Memory and Language 46(3):441-517
    (doi:10.1006/jmla.2002.2864). Recollection and familiarity are separable
    retrieval processes: familiarity is fast and scales with a graded
    strength/similarity signal; recollection is a slower, threshold-like
    recovery of the study context.
  - Diana, Yonelinas & Ranganath (2007), "Imaging recollection and familiarity
    in the medial temporal lobe: a three-component model," Trends in Cognitive
    Sciences 11(9):379-386 (doi:10.1016/j.tics.2007.08.001). A
    medial-temporal-lobe division of labour: perirhinal cortex signals item
    familiarity, parahippocampal cortex encodes context, and the hippocampus
    binds item-to-context for recollection.

Design (pure business logic — no I/O). The familiarity signal is the MAX vector
cosine similarity between the query and the retrieved candidates — a single
a-contextual scalar, computed with NO context assembly (no entity graph, no
spreading activation, no reconstruction). Three primitives are exposed:

  (a) ``familiarity_score(similarities)`` — the max-similarity gate itself.
  (b) ``assess_familiarity(similarities)`` — the gate plus supporting scalars
      (mean, and the top1↔top2 margin that says whether one item clearly wins).
  (c) ``recollection_needed(signal)`` / ``triage(candidates, similarities)`` —
      the decision: familiarity is SUFFICIENT only when it is overwhelming (max
      similarity over threshold AND a single clearly-dominant match); every
      weaker case needs slow contextual recollection. ``triage`` additionally
      annotates each candidate with its per-candidate familiarity without
      changing order or membership.

Honesty note (zetetic standard, matching value_learning.py / source_monitoring.py
/ attentional_control.py): "familiarity" here is a max-vector-cosine-similarity
HEURISTIC, and "recollection" is the pre-existing rerank chain — this is NOT a
trained dual-process model (no ROC / dual-process-signal-detection fit à la
Yonelinas, no separately-parameterised familiarity vs. recollection estimators).
The threshold and margin are fixed engineering constants, not values learned
against a task-performance signal. The mapping to neuroscience is structural
(a fast a-contextual scalar gate before slow contextual reconstruction), not a
claim that the max-similarity value equals a perirhinal familiarity strength.
The default triage does NOT skip recollection — it only annotates; the
latency-saving short-circuit is opt-in and fires only on an overwhelming,
unambiguous familiarity hit, so it never silently changes what a normal recall
returns.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Constants (fixed engineering defaults — NOT learned) ────────────────────
# Above this max cosine similarity a single candidate is "familiar enough" that
# its prior-exposure signal is unambiguous. Deliberately high: cosine ~0.92 is a
# near-duplicate / almost-exact match, the regime where a-contextual familiarity
# alone is trustworthy. Below it, the graded familiarity signal is not decisive
# and contextual recollection is required (Yonelinas 2002: familiarity is graded;
# only its high tail behaves like a clean old/new signal).
FAMILIARITY_THRESHOLD: float = 0.92

# The top-1 similarity must beat the top-2 by at least this margin for the hit to
# count as a *single clearly-dominant* match. Guards against the case where many
# candidates are all highly similar (a diffuse, ambiguous set) — that is exactly
# when recollection is needed to pick among them, not when familiarity suffices.
# Waived for a singleton candidate set (nothing competes).
FAMILIARITY_MARGIN: float = 0.10

# Method tags for the FamiliaritySignal.method field.
METHOD_VECTOR = "vector"  # faithful: max cosine over real embeddings
METHOD_SCORE_PROXY = "score_proxy"  # fallback: fused WRRF score, never skips
METHOD_EMPTY = "empty"  # no candidates / no similarities
METHOD_DISABLED = "disabled"  # ablation guard fired upstream

# source: structural — a top1↔top2 margin exists only when at least two
# candidates compete
_MIN_CANDIDATES_FOR_MARGIN = 2


@dataclass
class FamiliaritySignal:
    """The a-contextual familiarity read over a candidate set.

    ``familiarity`` — MAX similarity (the fast a-contextual gate; Yonelinas 2002).
    ``mean``        — mean similarity across the set (a diffuse-vs-peaked proxy).
    ``margin``      — top1 − top2 similarity; how clearly one item wins. Equals
                      ``familiarity`` for a singleton set (no competitor).
    ``n``           — number of similarity values the signal was computed over.
    ``method``      — how the similarities were obtained (see METHOD_* tags);
                      only ``METHOD_VECTOR`` is faithful enough to permit a
                      recollection short-circuit.
    """

    familiarity: float
    mean: float
    margin: float
    n: int
    method: str = METHOD_VECTOR


def familiarity_signal_as_dict(signal: "FamiliaritySignal") -> dict:
    """A free function, not a method: mutmut categorically excludes the
    body of any `@dataclass`-decorated class (`mutmut/mutation/
    file_mutation.py:236`), so logic placed on `FamiliaritySignal` methods
    would carry zero mutation coverage no matter how the test loader names
    the module (issue #262 3rd pass; issue #282).
    """
    return {
        "familiarity": round(signal.familiarity, 6),
        "mean": round(signal.mean, 6),
        "margin": round(signal.margin, 6),
        "n": signal.n,
        "method": signal.method,
    }


@dataclass
class TriageResult:
    """The outcome of an early familiarity triage over a candidate set.

    ``candidates``          — the candidate dicts, each annotated with its own
                              ``familiarity`` (when similarities align 1:1);
                              order and membership are UNCHANGED.
    ``signal``              — the set-level FamiliaritySignal.
    ``recollection_needed`` — True iff the query needs slow contextual
                              recollection (the default assumption).
    ``shortcut``            — True iff the caller opted in AND familiarity is
                              overwhelming AND the signal is a faithful vector
                              read: recollection may be skipped for latency.
                              False by default so recall output never changes.
    """

    candidates: list[dict]
    signal: FamiliaritySignal
    recollection_needed: bool
    shortcut: bool = False


# ── (a) the gate ────────────────────────────────────────────────────────────
def familiarity_score(similarities: list[float]) -> float:
    """The a-contextual familiarity gate: MAX similarity over the set.

    A single scalar of prior-exposure strength (Yonelinas 2002), computed with
    no context assembly. Returns 0.0 for an empty set.
    """
    if not similarities:
        return 0.0
    return max(float(s) for s in similarities)


# ── (b) the full signal ───────────────────────────────────────────────────────
def assess_familiarity(
    similarities: list[float],
    *,
    method: str = METHOD_VECTOR,
) -> FamiliaritySignal:
    """Compute the familiarity gate plus its supporting scalars.

    ``similarities`` is a per-candidate similarity list (cosine in [-1, 1] for
    the vector method). Empty input yields a zeroed signal tagged
    ``METHOD_EMPTY``.
    """
    sims = [float(s) for s in similarities]
    n = len(sims)
    if n == 0:
        return FamiliaritySignal(0.0, 0.0, 0.0, 0, METHOD_EMPTY)
    ordered = sorted(sims, reverse=True)
    top = ordered[0]
    mean = sum(sims) / n
    # top1 − top2; for a singleton there is no competitor, so margin = top.
    margin = ordered[0] - ordered[1] if n >= _MIN_CANDIDATES_FOR_MARGIN else ordered[0]
    return FamiliaritySignal(top, mean, margin, n, method)


# ── (c) the decision ──────────────────────────────────────────────────────────
def recollection_needed(
    signal: FamiliaritySignal,
    *,
    threshold: float = FAMILIARITY_THRESHOLD,
    margin: float = FAMILIARITY_MARGIN,
) -> bool:
    """True iff the query needs slow contextual recollection.

    Familiarity is SUFFICIENT (recollection NOT needed) only when it is
    overwhelming and unambiguous:
      - the signal is a faithful vector read (``METHOD_VECTOR``), AND
      - max similarity >= ``threshold``, AND
      - a single candidate clearly wins: either there is only one candidate,
        or the top1↔top2 ``margin`` >= ``margin``.
    Every weaker or non-vector case returns True — recollection is the default.
    This asymmetry is deliberate: the cheap familiarity gate may only *skip*
    reconstruction on an unmistakable hit, never on a marginal one.
    """
    if signal.n == 0:
        return True
    if signal.method != METHOD_VECTOR:
        # A proxy signal (e.g. fused WRRF score) is not an a-contextual vector
        # similarity; we do not trust it to license skipping recollection.
        return True
    dominant = signal.n < _MIN_CANDIDATES_FOR_MARGIN or signal.margin >= margin
    sufficient = signal.familiarity >= threshold and dominant
    return not sufficient


def triage(
    candidates: list[dict],
    similarities: list[float],
    *,
    allow_shortcut: bool = False,
    threshold: float = FAMILIARITY_THRESHOLD,
    margin: float = FAMILIARITY_MARGIN,
    method: str = METHOD_VECTOR,
) -> TriageResult:
    """Early familiarity triage over a candidate set (C2).

    ALWAYS annotates each candidate with its per-candidate ``familiarity`` (the
    similarity that fed the gate) when ``similarities`` aligns 1:1 with
    ``candidates`` — order and membership are preserved exactly. It computes the
    set-level FamiliaritySignal and the ``recollection_needed`` decision.

    ``shortcut`` is True ONLY when the caller passes ``allow_shortcut=True`` AND
    familiarity is overwhelming AND the signal is a faithful vector read. With
    the default ``allow_shortcut=False`` the result never licenses skipping
    recollection, so a caller that always runs the full chain sees an unchanged
    (only annotated) candidate list.

    Pure: fetches nothing. The caller supplies the similarities (see
    ``recall_pipeline.familiarity_triage`` for the bulk-embedding read that
    produces them).
    """
    signal = assess_familiarity(similarities, method=method)
    aligned = len(similarities) == len(candidates)
    annotated: list[dict] = []
    for i, c in enumerate(candidates):
        c_out = dict(c)
        if aligned:
            c_out["familiarity"] = round(float(similarities[i]), 6)
        annotated.append(c_out)
    rec = recollection_needed(signal, threshold=threshold, margin=margin)
    shortcut = bool(allow_shortcut and not rec and signal.method == METHOD_VECTOR)
    return TriageResult(
        candidates=annotated,
        signal=signal,
        recollection_needed=rec,
        shortcut=shortcut,
    )
