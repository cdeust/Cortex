"""Emotional tagging — priority encoding for emotionally salient memories.

Detects emotional markers in content using VADER compound sentiment
(Hutto & Gilbert 2014) combined with domain-specific keyword co-occurrence.
Emotionally tagged memories get higher importance and resist decay,
consistent with the general finding that emotional memories consolidate
better (McGaugh 2004, "The amygdala modulates the consolidation of
memories of emotionally arousing experiences", Annual Review of
Neuroscience).

Arousal inverted-U: implemented as a * arousal * exp(-b * arousal),
peak at arousal ≈ 1/b. The arousal-performance tradeoff is usually
credited to Yerkes & Dodson (1908), but that study measured optimal
stimulus intensity vs. task difficulty in mice and never plotted an
inverted-U against arousal; the arousal inverted-U ("Hebb's curve") is
Hebb (1955). This smooth c*a*exp(-b*a) parameterization is a modern
functional form, not from either paper.

Emotion detection uses VADER compound score (Hutto & Gilbert 2014) to
derive five emotion categories from compound polarity + domain keyword
co-occurrence. Constants (thresholds, scaling factors) are hand-tuned.

Pure business logic — no I/O.
"""

from __future__ import annotations

import math
import re
from typing import Any

from mcp_server.shared.vader import vader_compound
from mcp_server.core.ablation import Mechanism, is_mechanism_disabled

# Arousal below this floor gives no decay resistance.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_MIN_AROUSAL_FOR_RESISTANCE = 0.1

# Arousal above this threshold marks a memory as emotionally significant.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_EMOTIONAL_AROUSAL_THRESHOLD = 0.2

# ── Domain keyword sets for emotion classification ────────────────────────
# These co-occur with VADER polarity to disambiguate emotion categories.

_ERROR_DOMAIN_RE = re.compile(
    r"\b(error|exception|traceback|failed|failure|bug|crash|broken|timeout|"
    r"denied|rejected|deprecated|hours? debugging|still broken|"
    r"keeps? failing|won'?t work)\b",
    re.IGNORECASE,
)

_SUCCESS_DOMAIN_RE = re.compile(
    r"\b(fixed|resolved|working|success|passed|deployed|completed|shipped|"
    r"merged|approved|nailed|breakthrough|elegant|beautiful|clean|perfect|"
    r"excellent|awesome|improvement)\b",
    re.IGNORECASE,
)

_QUESTION_MARKERS_RE = re.compile(
    r"\?|"
    r"\b(confus|unclear|don'?t understand|makes no sense|"
    r"weird|bizarre|unexpected|strange|mysterious|puzzling|"
    r"why does|how come|what the)\b",
    re.IGNORECASE,
)

_URGENCY_DOMAIN_RE = re.compile(
    r"\b(urgent|critical|blocking|deadline|asap|immediately|"
    r"production|outage|down|hotfix|p0|sev[- ]?1)\b",
    re.IGNORECASE,
)

_INSIGHT_DOMAIN_RE = re.compile(
    r"\b(realized|discovered|found out|turns out|TIL|"
    r"interesting|insight|key finding|important lesson|"
    r"aha|eureka|lightbulb)\b",
    re.IGNORECASE,
)


def detect_emotions(content: str) -> dict[str, float]:
    """VADER-derived emotion detection (Hutto & Gilbert 2014).

    Uses VADER compound score as the base polarity signal, then derives
    five emotion categories from compound + domain keyword co-occurrence:
      - frustration: negative compound + error-domain keywords
      - satisfaction: positive compound + success-domain keywords
      - confusion: low |compound| + question markers
      - urgency: negative compound + urgency keywords
      - discovery: positive compound + insight keywords

    Returns emotion intensities in [0, 1]. Multiple can co-occur.
    """
    compound = vader_compound(content)
    abs_compound = abs(compound)

    # Count domain keyword hits (capped at 3 for normalization)
    error_hits = min(len(_ERROR_DOMAIN_RE.findall(content)), 3)
    success_hits = min(len(_SUCCESS_DOMAIN_RE.findall(content)), 3)
    question_hits = min(len(_QUESTION_MARKERS_RE.findall(content)), 3)
    urgency_hits = min(len(_URGENCY_DOMAIN_RE.findall(content)), 3)
    insight_hits = min(len(_INSIGHT_DOMAIN_RE.findall(content)), 3)

    # frustration: negative compound weighted by error-domain keywords
    frustration = 0.0
    if compound < 0 and error_hits > 0:
        frustration = abs_compound * (error_hits / 3.0)
    elif error_hits >= 1:
        # Keywords present but compound not negative — weaker signal
        frustration = 0.2 * (error_hits / 3.0)

    # satisfaction: positive compound weighted by success-domain keywords
    satisfaction = 0.0
    if compound > 0 and success_hits > 0:
        satisfaction = abs_compound * (success_hits / 3.0)
    elif success_hits >= 1:
        # Keywords present but compound not positive — weaker signal
        satisfaction = 0.2 * (success_hits / 3.0)

    # confusion: low absolute compound + question markers
    confusion = 0.0
    if question_hits > 0:
        # Lower certainty (abs_compound) amplifies confusion
        certainty_factor = max(0.0, 1.0 - abs_compound * 2)
        confusion = certainty_factor * (question_hits / 3.0)

    # urgency: negative compound weighted by urgency keywords
    urgency = 0.0
    if urgency_hits > 0:
        neg_weight = max(0.3, abs_compound) if compound <= 0 else 0.3
        urgency = neg_weight * (urgency_hits / 3.0)

    # discovery: positive compound weighted by insight keywords
    discovery = 0.0
    if insight_hits > 0:
        pos_weight = max(0.3, abs_compound) if compound >= 0 else 0.3
        discovery = pos_weight * (insight_hits / 3.0)

    return {
        "frustration": round(min(1.0, frustration), 4),
        "satisfaction": round(min(1.0, satisfaction), 4),
        "confusion": round(min(1.0, confusion), 4),
        "urgency": round(min(1.0, urgency), 4),
        "discovery": round(min(1.0, discovery), 4),
    }


def compute_arousal(emotions: dict[str, float]) -> float:
    """RMS of emotion intensities. Engineering heuristic — no paper.

    Arousal = combined emotional intensity regardless of valence.
    Used for Yerkes-Dodson modulation.

    Returns value in [0, 1].
    """
    values = [v for v in emotions.values() if v > 0]
    if not values:
        return 0.0
    # RMS of emotion intensities — captures total emotional energy
    rms = (sum(v * v for v in values) / len(values)) ** 0.5
    return round(min(1.0, rms), 4)


def compute_emotional_valence(emotions: dict[str, float]) -> float:
    """Compute emotional valence from detected emotions.

    Positive: satisfaction, discovery
    Negative: frustration, urgency
    Neutral: confusion

    Returns value in [-1, 1].
    """
    positive = emotions.get("satisfaction", 0) + emotions.get("discovery", 0)
    negative = emotions.get("frustration", 0) + emotions.get("urgency", 0)
    total = positive + negative + emotions.get("confusion", 0)

    if total == 0:
        return 0.0

    return round(max(-1.0, min(1.0, (positive - negative) / max(total, 1.0))), 4)


def arousal_inverted_u_bump(
    arousal: float,
    *,
    peak: float = 0.7,
    peak_height: float = 0.57,
) -> float:
    """The arousal inverted-U (Hebb's curve) as a bump ABOVE zero.

    Returns ``c * a * exp(-b * a)`` with ``b = 1/peak`` and ``c`` chosen so the
    bump attains ``peak_height`` at ``a = peak`` (``c = peak_height * b * e``).
    The full importance multiplier is ``1.0 + arousal_inverted_u_bump(a)``.

    With the defaults (peak=0.7, peak_height=0.57) this is byte-for-byte the
    curve ``compute_importance_boost`` used inline before it was factored out:
    b = 1/0.7 ≈ 1.4286, c ≈ 2.213, peak value 1.0 + 0.57 = 1.57 at a = 0.7.

    The arousal inverted-U is Hebb's curve (Hebb 1955, "Drives and the C.N.S.
    (conceptual nervous system)," Psychological Review 62:243-254,
    doi:10.1037/h0041823); Yerkes & Dodson (1908) established the
    stimulus-intensity/task-difficulty tradeoff but did not measure arousal.
    This smooth ``c*a*exp(-b*a)`` form is a modern parameterization, not from
    either paper. Factored here so stress_modulation.py (D1) can reuse the exact
    same bump rather than re-deriving the constants.

    Returns a non-negative bump (0 at arousal 0, → 0 as arousal → ∞).
    """
    b = 1.0 / peak
    c = peak_height * b * math.e
    return c * arousal * math.exp(-b * arousal)


def compute_importance_boost(
    emotions: dict[str, float],
    arousal: float,
) -> float:
    """Compute importance multiplier from emotional tagging.

    Arousal inverted-U: f(a) = c * a * exp(-b * a) + 1.0
    where a = arousal, b controls peak location, c scales amplitude.
    With b=1.43 (peak at a=1/b≈0.7), c≈2.213 (peak value ≈ 1.57).
    The arousal inverted-U is Hebb's curve (Hebb 1955); Yerkes & Dodson
    (1908) established the stimulus-intensity/difficulty tradeoff but did
    not measure arousal. This smooth c*a*exp(-b*a) form is a modern
    parameterization, not from either paper.

    Specific emotion bonuses are engineering heuristics (no paper):
    - Urgency: +0.3 (critical events must be remembered)
    - Discovery: +0.2 (insights are valuable)
    - Frustration: +0.1 (errors teach lessons)

    Returns multiplier in [1.0, 2.0].
    """

    if is_mechanism_disabled(Mechanism.EMOTIONAL_TAGGING):
        # No-op: base priority (no Yerkes-Dodson modulation).
        return 1.0

    # Smooth Yerkes-Dodson: f(a) = 1.0 + c * a * exp(-b * a)
    # b = 1/0.7 ≈ 1.4286 => peak at arousal = 0.7; c ≈ 2.213 => peak value 1.57.
    # The bump is factored into arousal_inverted_u_bump so stress_modulation.py
    # (D1) reuses the identical Hebb curve; defaults reproduce this exactly.
    yd_curve = 1.0 + arousal_inverted_u_bump(arousal)

    # Specific emotion bonuses
    bonus = 0.0
    bonus += emotions.get("urgency", 0) * 0.3
    bonus += emotions.get("discovery", 0) * 0.2
    bonus += emotions.get("frustration", 0) * 0.1

    return round(min(2.0, max(1.0, yd_curve + bonus)), 4)


def compute_decay_resistance(
    emotions: dict[str, float],
    arousal: float,
) -> float:
    """Compute decay resistance multiplier from emotional tagging.

    Emotionally tagged memories resist compression and decay.
    Higher value = slower decay.

    Returns multiplier in [1.0, 2.0].
    """

    if is_mechanism_disabled(Mechanism.EMOTIONAL_DECAY):
        # No-op: no emotion-modulated decay slowdown.
        return 1.0
    if arousal < _MIN_AROUSAL_FOR_RESISTANCE:
        return 1.0

    # All emotions contribute to decay resistance
    resistance = 1.0 + arousal * 0.6

    # Discovery and urgency are especially persistent
    resistance += emotions.get("discovery", 0) * 0.2
    resistance += emotions.get("urgency", 0) * 0.2

    return round(min(2.0, resistance), 4)


def tag_memory_emotions(content: str) -> dict[str, Any]:
    """Full emotional tagging pipeline for a memory.

    Returns all emotional metadata needed for storage.
    """
    emotions = detect_emotions(content)
    arousal = compute_arousal(emotions)
    valence = compute_emotional_valence(emotions)
    importance_boost = compute_importance_boost(emotions, arousal)
    decay_resistance = compute_decay_resistance(emotions, arousal)

    # Is this memory emotionally significant?
    is_emotional = arousal > _EMOTIONAL_AROUSAL_THRESHOLD

    # Dominant emotion
    dominant = max(emotions, key=lambda k: emotions[k]) if is_emotional else "neutral"

    return {
        "emotions": emotions,
        "arousal": arousal,
        "valence": valence,
        "importance_boost": importance_boost,
        "decay_resistance": decay_resistance,
        "is_emotional": is_emotional,
        "dominant_emotion": dominant,
    }
