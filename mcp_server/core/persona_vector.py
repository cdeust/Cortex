"""Extended 12D persona vector (9 numeric + 3 categorical).

Dimensions 1-3: activeReflective, sensingIntuitive, sequentialGlobal (CognitiveStyle)
Dimensions 4-9: thoroughness, autonomy, verbosity, riskTolerance, focusScope, iterationSpeed
"""

from __future__ import annotations

from typing import Any

from mcp_server.shared.linear_algebra import add, cosine_similarity, scale, zeros

PERSONA_DIMENSIONS = [
    "activeReflective",
    "sensingIntuitive",
    "sequentialGlobal",
    "thoroughness",
    "autonomy",
    "verbosity",
    "riskTolerance",
    "focusScope",
    "iterationSpeed",
]


def _clamp(v: float) -> float:
    return max(-1.0, min(1.0, v))


def _normalize_signal(value: float, low: float, high: float) -> float:
    """Map value to [-1, 1]: below low=-1, above high=+1, linear between."""
    if value > high:
        return 1.0
    if value < low:
        return -1.0
    mid = (low + high) / 2
    half_range = (high - low) / 2
    return (value - mid) / half_range


def _compute_behavioral_dims(ss: dict, tp: dict) -> dict[str, float]:
    """Compute the 6 behavioral persona dimensions from session and tool data."""
    avg_duration = ss.get("avgDuration") or 0
    avg_turns = ss.get("avgTurns") or 0
    duration_signal = _normalize_signal(avg_duration, 300000, 1800000)
    turns_signal = _normalize_signal(avg_turns, 5, 30)
    thoroughness = _clamp((duration_signal + turns_signal) / 2)

    agent_ratio = (tp.get("Agent") or {}).get("ratio", 0)
    bash_ratio = (tp.get("Bash") or {}).get("ratio", 0)
    autonomy = _clamp((agent_ratio * 2 + bash_ratio) - 0.5)

    avg_messages = ss.get("avgMessages") or 0
    verbosity = _clamp(_normalize_signal(avg_messages, 5, 20) * 0.5)

    edit_ratio = (tp.get("Edit") or {}).get("ratio", 0)
    read_ratio = (tp.get("Read") or {}).get("ratio", 0)
    risk_tolerance = _clamp((edit_ratio - read_ratio) * 2)

    glob_ratio = (tp.get("Glob") or {}).get("ratio", 0)
    grep_ratio = (tp.get("Grep") or {}).get("ratio", 0)
    focus_scope = _clamp((glob_ratio + grep_ratio) * 2 - 0.5)

    burst_ratio = ss.get("burstRatio") or 0
    iteration_speed = _clamp(_normalize_signal(burst_ratio, 0.3, 0.7) * 0.8)

    return {
        "thoroughness": thoroughness,
        "autonomy": autonomy,
        "verbosity": verbosity,
        "riskTolerance": risk_tolerance,
        "focusScope": focus_scope,
        "iterationSpeed": iteration_speed,
    }


def build_persona_vector(profile: dict) -> dict[str, float]:
    mc = profile.get("metacognitive") or {}
    ss = profile.get("sessionShape") or {}
    tp = profile.get("toolPreferences") or {}

    result = {
        "activeReflective": mc.get("activeReflective") or 0,
        "sensingIntuitive": mc.get("sensingIntuitive") or 0,
        "sequentialGlobal": mc.get("sequentialGlobal") or 0,
    }
    result.update(_compute_behavioral_dims(ss, tp))
    return result


def persona_to_array(pv: dict) -> list[float]:
    return [pv.get(dim, 0) for dim in PERSONA_DIMENSIONS]


def persona_distance(a: dict, b: dict) -> float:
    return 1 - cosine_similarity(persona_to_array(a), persona_to_array(b))


def persona_drift(old_pv: dict, new_pv: dict) -> dict[str, Any]:
    old_arr = persona_to_array(old_pv)
    new_arr = persona_to_array(new_pv)

    direction: dict[str, float] = {}
    max_drift = 0.0
    max_dim = ""
    for i, dim in enumerate(PERSONA_DIMENSIONS):
        diff = new_arr[i] - old_arr[i]
        direction[dim] = round(diff * 100) / 100
        if abs(diff) > abs(max_drift):
            max_drift = diff
            max_dim = dim

    magnitude = 1 - cosine_similarity(old_arr, new_arr)

    dim_labels = {
        "activeReflective": ("more reflective", "more active"),
        "sensingIntuitive": ("more intuitive", "more sensing"),
        "sequentialGlobal": ("more global", "more sequential"),
        "thoroughness": ("quicker", "more thorough"),
        "autonomy": ("more guided", "more autonomous"),
        "verbosity": ("more terse", "more verbose"),
        "riskTolerance": ("more conservative", "bolder"),
        "focusScope": ("narrower focus", "broader scope"),
        "iterationSpeed": ("more deliberate", "faster iteration"),
    }

    labels = dim_labels.get(max_dim, ("shifted", "shifted"))
    interpretation = labels[0] if max_drift < 0 else labels[1]

    return {
        "magnitude": magnitude,
        "direction": direction,
        "interpretation": interpretation,
    }


def compose_personas(vectors: list[dict], weights: list[float]) -> dict[str, float]:
    if not vectors:
        return {dim: 0 for dim in PERSONA_DIMENSIONS}

    total_weight = sum(weights) or 1
    result = zeros(len(PERSONA_DIMENSIONS))

    for i, vec in enumerate(vectors):
        arr = persona_to_array(vec)
        w = (weights[i] if i < len(weights) else 0) / total_weight
        result = add(result, scale(arr, w))

    pv = {}
    for i, dim in enumerate(PERSONA_DIMENSIONS):
        pv[dim] = _clamp(round(result[i] * 100) / 100)
    return pv


def steer_context(
    base_context: str, persona_vector: dict, target_adjustments: dict | None = None
) -> str:
    if not target_adjustments:
        return base_context

    sentences = []
    drift_threshold = 0.2

    steering_map_pos = {
        "thoroughness": "Be more thorough and exhaustive.",
        "autonomy": "Take more initiative.",
        "verbosity": "Provide more detail.",
        "riskTolerance": "Try bolder approaches.",
        "focusScope": "Consider the broader picture.",
        "iterationSpeed": "Move faster, iterate quickly.",
    }
    steering_map_neg = {
        "thoroughness": "Be more concise and quick.",
        "autonomy": "Ask before acting.",
        "verbosity": "Keep responses brief.",
        "riskTolerance": "Prefer safe, incremental changes.",
        "focusScope": "Focus on the specific task.",
        "iterationSpeed": "Take time to think through each step.",
    }

    for dim, target in target_adjustments.items():
        current = persona_vector.get(dim)
        if current is None:
            continue
        diff = target - current
        if abs(diff) < drift_threshold:
            continue
        sentence = steering_map_pos.get(dim) if diff > 0 else steering_map_neg.get(dim)
        if sentence:
            sentences.append(sentence)

    if not sentences:
        return base_context
    return base_context + " " + " ".join(sentences)
