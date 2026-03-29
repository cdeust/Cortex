"""Extract tool preferences and session shape from conversation data.

Tool stats: ratio + avg-per-session. Session shape: burst / exploration / mixed.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Tool Preferences
# ---------------------------------------------------------------------------


def _count_tools_in_session(tools_used: list) -> dict[str, int]:
    """Count tool usage from a single session's tools_used list."""
    counts: dict[str, int] = {}
    for entry in tools_used:
        if isinstance(entry, str):
            counts[entry] = counts.get(entry, 0) + 1
        elif isinstance(entry, dict):
            name = entry.get("name") or entry.get("tool") or entry.get("toolName")
            count = entry.get("count") or entry.get("uses") or 1
            if name:
                counts[name] = counts.get(name, 0) + count
    return counts


def extract_tool_preferences(conversations: list[dict]) -> dict[str, dict[str, float]]:
    """Compute per-tool ratio and avg-per-session across all conversations."""
    total_sessions = len(conversations)
    if total_sessions == 0:
        return {}

    tool_stats: dict[str, dict] = {}

    for session_idx, conv in enumerate(conversations):
        tools_used = conv.get("toolsUsed") or conv.get("tools_used") or []
        if not isinstance(tools_used, list):
            continue

        counts = _count_tools_in_session(tools_used)

        for tool_name, count in counts.items():
            if tool_name not in tool_stats:
                tool_stats[tool_name] = {"sessions_using": set(), "total_uses": 0}
            stat = tool_stats[tool_name]
            stat["sessions_using"].add(session_idx)
            stat["total_uses"] += count

    result = {}
    for tool_name, stat in tool_stats.items():
        sessions_using_count = len(stat["sessions_using"])
        avg = (
            stat["total_uses"] / sessions_using_count if sessions_using_count > 0 else 0
        )
        result[tool_name] = {
            "ratio": sessions_using_count / total_sessions,
            "avgPerSession": avg,
        }

    return dict(sorted(result.items(), key=lambda x: x[1]["ratio"], reverse=True))


# ---------------------------------------------------------------------------
# Session Shape
# ---------------------------------------------------------------------------

_BURST_THRESHOLD_MS = 600_000
_EXPLORATION_THRESHOLD_TURNS = 20


def _empty_shape() -> dict[str, Any]:
    return {
        "avgDuration": 0,
        "avgTurns": 0,
        "avgMessages": 0,
        "burstRatio": 0,
        "explorationRatio": 0,
        "dominantMode": "mixed",
    }


def _parse_session_metrics(conv: dict) -> tuple[int, int, int]:
    """Extract duration, turn count, and message count from a conversation."""
    duration = conv.get("duration") or conv.get("durationMs") or 0
    turn_count = conv.get("turnCount") or conv.get("turns") or 0

    message_count = conv.get("messageCount") or 0
    if message_count == 0:
        msgs = conv.get("messages")
        if isinstance(msgs, list):
            message_count = len(msgs)

    return duration, turn_count, message_count


def _classify_dominant_mode(burst_ratio: float, exploration_ratio: float) -> str:
    if burst_ratio > 0.6:
        return "burst"
    if exploration_ratio > 0.6:
        return "exploration"
    return "mixed"


def extract_session_shape(conversations: list[dict]) -> dict[str, Any]:
    """Classify session shape (burst/exploration/mixed) from conversation metadata."""
    total = len(conversations)
    if total == 0:
        return _empty_shape()

    duration_sum = 0
    turns_sum = 0
    messages_sum = 0
    burst_count = 0
    exploration_count = 0

    for conv in conversations:
        duration, turn_count, message_count = _parse_session_metrics(conv)

        duration_sum += duration
        turns_sum += turn_count
        messages_sum += message_count

        if duration < _BURST_THRESHOLD_MS:
            burst_count += 1
        if turn_count > _EXPLORATION_THRESHOLD_TURNS:
            exploration_count += 1

    burst_ratio = burst_count / total
    exploration_ratio = exploration_count / total

    return {
        "avgDuration": duration_sum / total,
        "avgTurns": turns_sum / total,
        "avgMessages": messages_sum / total,
        "burstRatio": burst_ratio,
        "explorationRatio": exploration_ratio,
        "dominantMode": _classify_dominant_mode(burst_ratio, exploration_ratio),
    }
