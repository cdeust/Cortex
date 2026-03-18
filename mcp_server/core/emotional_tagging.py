"""Emotional tagging — amygdala-inspired priority encoding.

Based on Wang & Bhatt (Nature Human Behaviour, 2024) and the emotional
tagging hypothesis: high-frequency activity in the amygdala during encoding
of emotional events strengthens hippocampal memory traces.

In JARVIS: detect emotional markers in content (frustration from errors,
satisfaction from fixes, confusion from debugging), multiply importance
and reduce decay rate. Emotionally tagged memories resist compression.

Also implements the Yerkes-Dodson inverted U: moderate arousal enhances
memory, but extreme arousal can impair it.

Pure business logic — no I/O.
"""

from __future__ import annotations

import re
from typing import Any

# ── Emotion detection patterns ────────────────────────────────────────────

_FRUSTRATION_RE = re.compile(
    r"\b(frustrat|annoying|painful|struggle|nightmare|horrible|"
    r"waste of time|hate|awful|terrible|ugh|argh|damn|wtf|"
    r"hours? debugging|still broken|keeps? failing|won'?t work)\b",
    re.IGNORECASE,
)

_SATISFACTION_RE = re.compile(
    r"\b(finally|breakthrough|elegant|beautiful|clean|nailed it|"
    r"perfect|works great|happy with|proud|satisf|excellent|"
    r"much better|huge improvement|love this|awesome)\b",
    re.IGNORECASE,
)

_CONFUSION_RE = re.compile(
    r"\b(confus|unclear|don'?t understand|makes no sense|"
    r"weird|bizarre|unexpected|strange|mysterious|puzzling|"
    r"why does|how come|what the)\b",
    re.IGNORECASE,
)

_URGENCY_RE = re.compile(
    r"\b(urgent|critical|blocking|deadline|asap|immediately|"
    r"production|outage|down|broken in prod|hotfix|p0|sev[- ]?1)\b",
    re.IGNORECASE,
)

_DISCOVERY_RE = re.compile(
    r"\b(realized|discovered|found out|turns out|TIL|"
    r"interesting|insight|key finding|important lesson|"
    r"aha|eureka|lightbulb)\b",
    re.IGNORECASE,
)


def detect_emotions(content: str) -> dict[str, float]:
    """Detect emotional signals in content.

    Returns emotion intensities normalized to [0, 1].
    Multiple emotions can co-occur (e.g., frustration + urgency).
    """
    frustration = min(len(_FRUSTRATION_RE.findall(content)) / 3.0, 1.0)
    satisfaction = min(len(_SATISFACTION_RE.findall(content)) / 3.0, 1.0)
    confusion = min(len(_CONFUSION_RE.findall(content)) / 3.0, 1.0)
    urgency = min(len(_URGENCY_RE.findall(content)) / 2.0, 1.0)
    discovery = min(len(_DISCOVERY_RE.findall(content)) / 2.0, 1.0)

    return {
        "frustration": round(frustration, 4),
        "satisfaction": round(satisfaction, 4),
        "confusion": round(confusion, 4),
        "urgency": round(urgency, 4),
        "discovery": round(discovery, 4),
    }


def compute_arousal(emotions: dict[str, float]) -> float:
    """Compute overall arousal from emotion signals.

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


def compute_importance_boost(
    emotions: dict[str, float],
    arousal: float,
) -> float:
    """Compute importance multiplier from emotional tagging.

    Yerkes-Dodson inverted U: moderate arousal enhances encoding,
    extreme arousal (> 0.9) slightly impairs it.

    Specific emotions have additional effects:
    - Urgency: +0.3 (critical events must be remembered)
    - Discovery: +0.2 (insights are valuable)
    - Frustration: +0.1 (errors teach lessons)

    Returns multiplier in [1.0, 2.0].
    """
    # Base Yerkes-Dodson: peaks at arousal ~0.7
    if arousal <= 0.7:
        yd_curve = 1.0 + arousal * 0.8  # Linear ramp to 1.56 at 0.7
    else:
        yd_curve = 1.56 - (arousal - 0.7) * 0.5  # Gentle decline after peak

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
    if arousal < 0.1:
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
    is_emotional = arousal > 0.2

    # Dominant emotion
    dominant = max(emotions, key=emotions.get) if is_emotional else "neutral"

    return {
        "emotions": emotions,
        "arousal": arousal,
        "valence": valence,
        "importance_boost": importance_boost,
        "decay_resistance": decay_resistance,
        "is_emotional": is_emotional,
        "dominant_emotion": dominant,
    }
