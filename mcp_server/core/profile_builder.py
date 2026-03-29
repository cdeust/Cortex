"""Profile building facade — backward-compatible re-exports + incremental update.

Full profile assembly is in profile_assembler.py.
This module provides apply_session_update for incremental EMA updates
and re-exports build_domain_profiles for backward compatibility.
"""

from __future__ import annotations

from datetime import datetime, timezone

from mcp_server.core.persona_vector import build_persona_vector
from mcp_server.core.style_classifier_ema import update_style_ema

# ---------------------------------------------------------------------------
# Incremental session update
# ---------------------------------------------------------------------------

_BURST_THRESHOLD_MS = 600_000
_EXPLORATION_THRESHOLD_TURNS = 20
_EMA_ALPHA = 0.1


def _update_session_shape(
    ss: dict,
    duration: int,
    turn_count: int,
    new_count: int,
) -> None:
    """Update session shape running averages in place."""
    ss["avgDuration"] = ss["avgDuration"] + (duration - ss["avgDuration"]) / new_count
    ss["avgTurns"] = ss["avgTurns"] + (turn_count - ss["avgTurns"]) / new_count

    is_burst = 1 if duration < _BURST_THRESHOLD_MS else 0
    ss["burstRatio"] = ss["burstRatio"] + (is_burst - ss["burstRatio"]) / new_count

    is_exploration = 1 if turn_count > _EXPLORATION_THRESHOLD_TURNS else 0
    ss["explorationRatio"] = (
        ss["explorationRatio"] + (is_exploration - ss["explorationRatio"]) / new_count
    )

    if ss["burstRatio"] > 0.6:
        ss["dominantMode"] = "burst"
    elif ss["explorationRatio"] > 0.6:
        ss["dominantMode"] = "exploration"
    else:
        ss["dominantMode"] = "mixed"


def _update_tool_preferences(
    tp: dict,
    tools_used: list[str],
    old_count: int,
    new_count: int,
) -> None:
    """Update tool preference ratios and averages in place."""
    tool_set = set(tools_used)
    for tool in tool_set:
        tool_count_in_session = sum(1 for t in tools_used if t == tool)
        if tool in tp:
            old_sessions_using = round(tp[tool]["ratio"] * old_count)
            tp[tool]["ratio"] = (old_sessions_using + 1) / new_count
            tp[tool]["avgPerSession"] = tp[tool]["avgPerSession"] + (
                tool_count_in_session - tp[tool]["avgPerSession"]
            ) / (old_sessions_using + 1)
        else:
            tp[tool] = {"ratio": 1 / new_count, "avgPerSession": tool_count_in_session}

    for tool in list(tp.keys()):
        if tool not in tool_set:
            old_sessions_using = round(tp[tool]["ratio"] * old_count)
            tp[tool]["ratio"] = old_sessions_using / new_count


def _build_style_observation(
    duration: int | None,
    tools_used: list[str],
) -> dict[str, float]:
    """Build a cognitive style observation from session signals."""
    observation: dict[str, float] = {}

    if duration is not None:
        if duration < _BURST_THRESHOLD_MS:
            observation["activeReflective"] = 0.5
        elif duration > 1_800_000:
            observation["activeReflective"] = -0.5
        else:
            observation["activeReflective"] = 0.0

    if tools_used:
        edit_count = sum(1 for t in tools_used if t in ("Edit", "Write"))
        read_count = sum(1 for t in tools_used if t in ("Read", "Grep"))
        total = len(tools_used)
        if edit_count / total > 0.4:
            observation["activeReflective"] = (
                observation.get("activeReflective", 0) + 0.3
            )
        if read_count / total > 0.4:
            observation["activeReflective"] = (
                observation.get("activeReflective", 0) - 0.3
            )

    if "activeReflective" in observation:
        observation["activeReflective"] = max(
            -1, min(1, observation["activeReflective"])
        )

    return observation


def _update_persona_vector(dp: dict) -> None:
    """EMA-update the persona vector in place."""
    pv = dp.get("personaVector")
    if not pv:
        return
    new_persona = build_persona_vector(dp)
    for dim in list(pv.keys()):
        if isinstance(pv.get(dim), (int, float)) and isinstance(
            new_persona.get(dim), (int, float)
        ):
            pv[dim] = max(
                -1, min(1, _EMA_ALPHA * new_persona[dim] + (1 - _EMA_ALPHA) * pv[dim])
            )


def _update_counts_and_metadata(dp: dict, new_count: int) -> None:
    """Update session count, timestamp, and confidence in place."""
    dp["sessionCount"] = new_count
    dp["lastUpdated"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    data_quality = min(new_count / 10, 1.0)
    dp["confidence"] = round(min(new_count / 50, 1.0) * data_quality * 100) / 100


def apply_session_update(
    *,
    domain_profile: dict,
    session_data: dict,
) -> dict:
    """Incrementally update a domain profile with a single new session."""
    dp = domain_profile
    duration = session_data.get("duration")
    tools_used = session_data.get("tools_used") or []
    turn_count = session_data.get("turn_count") or 0

    old_count = dp.get("sessionCount") or 0
    new_count = old_count + 1

    ss = dp.get("sessionShape")
    if ss and duration is not None:
        _update_session_shape(ss, duration, turn_count, new_count)

    tp = dp.get("toolPreferences")
    if tools_used and tp is not None:
        _update_tool_preferences(tp, tools_used, old_count, new_count)

    mc = dp.get("metacognitive")
    if mc:
        observation = _build_style_observation(duration, tools_used)
        dp["metacognitive"] = update_style_ema(mc, observation, _EMA_ALPHA)

    _update_persona_vector(dp)
    _update_counts_and_metadata(dp, new_count)

    return dp
