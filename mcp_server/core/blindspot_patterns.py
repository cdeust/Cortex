"""Pattern blind spot detection helpers.

Companion module to blindspot_detector.py — detects missing exploration,
deep-work, and quick-iteration session patterns by comparing domain
statistics against global averages.

Pure business logic — no I/O.
"""

from __future__ import annotations

from typing import Any


def check_exploration_gap(
    domain_exploration_ratio: float,
    global_exp_ratio: float,
) -> list[dict[str, Any]]:
    """Check for exploration session gaps vs global average."""
    if domain_exploration_ratio == 0 and global_exp_ratio >= 0.4:
        return [
            {
                "type": "pattern",
                "value": "exploration",
                "severity": "high",
                "description": (
                    "This domain has zero exploration sessions (research/architecture),"
                    f" while globally {global_exp_ratio * 100:.0f}% of sessions are exploratory."
                ),
                "suggestion": "Schedule dedicated research or architecture sessions to avoid tunnel vision.",
            }
        ]
    if (
        domain_exploration_ratio > 0
        and domain_exploration_ratio < global_exp_ratio * 0.25
        and global_exp_ratio >= 0.2
    ):
        return [
            {
                "type": "pattern",
                "value": "exploration",
                "severity": "medium",
                "description": (
                    f"Exploration ratio ({domain_exploration_ratio * 100:.1f}%) is significantly"
                    f" below global average ({global_exp_ratio * 100:.1f}%)."
                ),
                "suggestion": "Increase research/architecture sessions to keep up with global breadth.",
            }
        ]
    return []


def count_duration_buckets(conversations: list[dict]) -> tuple[int, int]:
    """Count short (<10 min) and long (>30 min) sessions."""
    short = 0
    long = 0
    for conv in conversations:
        dur = conv.get("durationMinutes") or conv.get("duration") or 0
        if dur > 0 and dur < 10:
            short += 1
        if dur > 30:
            long += 1
    return short, long


def check_duration_gaps(
    domain_total: int,
    domain_short: int,
    domain_long: int,
    global_short_ratio: float,
    global_long_ratio: float,
) -> list[dict[str, Any]]:
    """Check for missing deep-work or quick-iteration sessions."""
    gaps: list[dict[str, Any]] = []
    if domain_long / domain_total == 0 and global_long_ratio >= 0.3:
        gaps.append(
            {
                "type": "pattern",
                "value": "deep-work",
                "severity": "medium",
                "description": (
                    "No deep-work sessions (>30 min) found in this domain,"
                    f" while globally {global_long_ratio * 100:.0f}% of sessions are deep."
                ),
                "suggestion": "Allocate longer focused sessions for complex problems in this domain.",
            }
        )
    if domain_short / domain_total == 0 and global_short_ratio >= 0.3:
        gaps.append(
            {
                "type": "pattern",
                "value": "quick-iteration",
                "severity": "low",
                "description": (
                    "No short iteration sessions (<10 min) found in this domain,"
                    f" while globally {global_short_ratio * 100:.0f}% of sessions are short."
                ),
                "suggestion": "Consider quick experiment or fix sessions to build faster feedback loops.",
            }
        )
    return gaps
