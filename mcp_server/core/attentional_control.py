"""Central executive / attentional control (A1) — top-down selection over the
working set.

Baddeley's model of working memory has, besides its storage buffers, a *central
executive*: an attentional-control system that decides which of the currently-
held items are in focus for the task at hand. Cortex has the storage side (the
sensory buffer, a bounded working-memory ring) and a capacity ceiling (Cowan's
4±1, DEFAULT_MAX_CHUNKS in metacognition_analysis), but no allocation step —
nothing scores the buffered items against the current query and decides which
few are "in focus." Everything held is treated as equally available, which is
exactly what an attentional bottleneck is *not*.

Neuroscience basis (DOIs verified against Crossref):
  - Baddeley (2003), "Working memory: looking back and looking forward,"
    Nature Reviews Neuroscience 4:829-839 (doi:10.1038/nrn1201). The central
    executive as an attentional-control system over the working-memory buffers.
  - Posner & Petersen (1990), "The attention system of the human brain,"
    Annual Review of Neuroscience 13:25-42
    (doi:10.1146/annurev.ne.13.030190.000325). Attention as a separable network
    with a selective "spotlight" that can be directed top-down.
  - Cowan (2001), "The magical number 4 in short-term memory,"
    Behavioral and Brain Sciences 24:87-114 (doi:10.1017/S0140525X01003922).
    The focus of attention holds ~4 chunks — the capacity ceiling this module
    enforces via a local FOCUS_CAPACITY_DEFAULT = 4 (the centre of the same 4±1
    band metacognition_analysis.DEFAULT_MAX_CHUNKS = 5 encodes; not imported).

Mechanism. Content-based attention over a memory set is the transformer
operation itself: query-weighted soft selection. Each working-set item gets a
relevance score against the current query/task; a softmax over those scores
(a local pure-Python reimplementation of the same shift-by-max stabilization
hopfield.py uses, with an added temperature knob) yields an attention
distribution; a top-down *temperature* controls how sharply the
spotlight focuses (low temperature → winner-take-most concentration, high →
diffuse); the top-weighted items up to the Cowan ceiling are exposed as the
focus set. An optional bottom-up salience term (importance, |valence|) is added
to the top-down relevance, so an unbidden but salient item can still capture the
spotlight — the bottom-up/top-down interaction Posner & Petersen describe.

Honesty note (zetetic standard, matching value_learning.py / source_monitoring.py):
this is the standard content-based-attention soft-selection, not a *learned*
top-down controller — the temperature and the salience weight are fixed
engineering constants, not parameters trained against a task-performance signal.
The softmax is a small pure-Python reimplementation of the same shift-by-max
stabilization used by hopfield._softmax, with a temperature knob that hopfield's
fixed-beta variant does not expose (kept local so this module has no numpy
dependency). Relevance scoring here is lexical/feature overlap (the caller may
pass a precomputed semantic score instead); it does not itself embed or call a
model.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

# ── Constants ───────────────────────────────────────────────────────────────
# The focus of attention holds ~4 chunks (Cowan 2001). This is the same ceiling
# metacognition applies for chunking (metacognition_analysis.DEFAULT_MAX_CHUNKS
# = 5 = 4±1); here we take the centre of that band (4) as the focus size. Kept
# as a local constant so this module has no import dependency on metacognition.
FOCUS_CAPACITY_DEFAULT = 4

# Top-down control knob. The softmax temperature: <1 sharpens the spotlight
# (concentrates weight on the best matches), >1 diffuses it. 1.0 is the plain
# softmax. Fixed engineering default — not learned.
ATTENTION_TEMPERATURE = 0.5

# How much bottom-up salience (importance, |valence|) adds to top-down relevance.
# 0 = purely goal-driven attention; higher = more stimulus-driven capture.
SALIENCE_WEIGHT = 0.3

_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass
class AttentionAllocation:
    """The result of one attention-allocation pass.

    ``focus``      — the in-focus items (≤ capacity), highest-weight first, each
                     a dict with the original item plus ``attention_weight``.
    ``weights``    — attention weight per input item, in input order.
    ``entropy``    — Shannon entropy of the attention distribution (nats); low =
                     sharply focused, high = diffuse. A load/uncertainty proxy.
    ``capacity``   — the Cowan ceiling applied.
    ``overflow``   — count of items that were held but fell outside the focus.
    """

    focus: list[dict]
    weights: list[float]
    entropy: float
    capacity: int
    overflow: int = 0

    def as_dict(self) -> dict:
        return {
            "focus": self.focus,
            "weights": [round(w, 4) for w in self.weights],
            "entropy": round(self.entropy, 4),
            "capacity": self.capacity,
            "overflow": self.overflow,
        }


# ── Relevance scoring (top-down) ────────────────────────────────────────────
def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall((text or "").lower()))


def relevance_score(query: str, content: str) -> float:
    """Lexical top-down relevance of ``content`` to ``query`` in [0,1].

    Jaccard-style query coverage: fraction of query tokens present in the item.
    A caller with a semantic score (vector similarity) should pass it via
    ``precomputed_scores`` to allocate_attention instead of relying on this.
    """
    q = _tokens(query)
    if not q:
        return 0.0
    c = _tokens(content)
    if not c:
        return 0.0
    return len(q & c) / len(q)


# ── The softmax spotlight ───────────────────────────────────────────────────
def _softmax(logits: list[float], temperature: float) -> list[float]:
    """Numerically-stable softmax with temperature.

    Mirrors hopfield._softmax (same shift-by-max stabilization); kept as a small
    pure-Python version so this module has no hard numpy dependency, and applies
    the temperature scaling hopfield's fixed-beta variant does not expose.
    """
    if not logits:
        return []
    t = max(temperature, 1e-6)
    scaled = [x / t for x in logits]
    m = max(scaled)
    exps = [math.exp(x - m) for x in scaled]
    total = sum(exps)
    if total <= 0.0:
        n = len(logits)
        return [1.0 / n] * n
    return [e / total for e in exps]


def _entropy(weights: list[float]) -> float:
    """Shannon entropy (nats) of an attention distribution."""
    return -sum(w * math.log(w) for w in weights if w > 0.0)


# ── The allocation pass ─────────────────────────────────────────────────────
def allocate_attention(
    query: str,
    items: list[dict],
    *,
    capacity: int = FOCUS_CAPACITY_DEFAULT,
    temperature: float = ATTENTION_TEMPERATURE,
    salience_weight: float = SALIENCE_WEIGHT,
    precomputed_scores: list[float] | None = None,
) -> AttentionAllocation:
    """Direct the attentional spotlight over ``items`` given the current query.

    Each item (a dict with at least ``content``; optionally ``importance`` and
    ``valence``) is scored for top-down relevance to ``query`` (or the caller's
    ``precomputed_scores``), plus a bottom-up salience term. A temperature-scaled
    softmax turns the scores into an attention distribution; the top ``capacity``
    items (Cowan ceiling) become the focus set, each annotated with its weight.

    Empty input yields an empty allocation. Fewer items than capacity means all
    are in focus (with their relative weights).
    """
    n = len(items)
    if n == 0:
        return AttentionAllocation(focus=[], weights=[], entropy=0.0, capacity=capacity)

    if precomputed_scores is not None:
        if len(precomputed_scores) != n:
            raise ValueError("precomputed_scores length must match items")
        top_down = list(precomputed_scores)
    else:
        top_down = [relevance_score(query, it.get("content", "")) for it in items]

    # Bottom-up salience: importance + |valence|, scaled. Lets an unbidden but
    # salient item compete for the spotlight (stimulus-driven capture).
    logits: list[float] = []
    # strict=True: top_down is built one score per item three lines above,
    # so the lengths are always equal by construction. Documented
    # equivalent mutant (coding-standards.md §12.1): allocate_attention's
    # earlier `if len(precomputed_scores) != n: raise` (see above) makes a
    # top_down/items length mismatch unreachable through this function's
    # public entry point, so no test can distinguish strict=True from
    # strict=False/None here without bypassing that guard directly.
    for score, it in zip(top_down, items, strict=True):
        importance = float(it.get("importance", 0.0) or 0.0)
        valence = abs(float(it.get("valence", 0.0) or 0.0))
        salience = 0.5 * importance + 0.5 * valence
        logits.append(score + salience_weight * salience)

    weights = _softmax(logits, temperature)
    entropy = _entropy(weights)

    order = sorted(range(n), key=lambda i: weights[i], reverse=True)
    focus_idx = order[: max(capacity, 0)]
    focus = []
    for i in focus_idx:
        item = dict(items[i])
        item["attention_weight"] = round(weights[i], 4)
        focus.append(item)

    return AttentionAllocation(
        focus=focus,
        weights=weights,
        entropy=entropy,
        capacity=capacity,
        overflow=max(n - len(focus_idx), 0),
    )


def in_focus_contents(allocation: AttentionAllocation) -> list[str]:
    """Convenience: the ``content`` strings of the in-focus items, best first."""
    return [f.get("content", "") for f in allocation.focus]
