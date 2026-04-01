"""Replay sequence selection and priority scoring.

Selects which replay sequences fire during an SWR burst based on a
priority score. Higher-priority sequences are replayed first.

Priority formula: (avg_heat * 0.4 + sqrt(heat_variance) * 0.6) * DA_level.
This is a hand-tuned heuristic combining importance (heat) and surprise
(variance), amplified by dopamine level. No paper — engineering decision.

The DA modulation captures Schultz's qualitative finding that dopamine
amplifies replay of rewarding experiences, but the specific formula is
not the Schultz/Rescorla-Wagner RPE equation.

All constants (0.4/0.6 weights, threshold 0.3, max 5) are hand-tuned.

Pure business logic — no I/O.
"""

from __future__ import annotations

import math

from mcp_server.core.replay_types import (
    ReplayDirection,
    ReplayEvent,
    ReplaySequence,
)

# ── Constants ────────────────────────────────────────────────────────────

_PRIORITY_THRESHOLD = 0.3
_MAX_SEQUENCES_PER_SWR = 5


# ── Priority Scoring ────────────────────────────────────────────────────


def compute_sequence_priority(
    events: list[ReplayEvent],
    dopamine_level: float = 1.0,
) -> float:
    """Compute priority score for a replay sequence.

    Formula: (avg_heat * 0.4 + sqrt(heat_variance) * 0.6) * DA_level.
    Heuristic combining importance (heat) and surprise (variance),
    amplified by dopamine. Weights are hand-tuned — no paper.

    Returns:
        Priority score in [0, 1].
    """
    if len(events) < 2:
        return 0.0

    heats = [e.heat for e in events]
    avg_heat = sum(heats) / len(heats)
    variance = sum((h - avg_heat) ** 2 for h in heats) / len(heats)
    raw_priority = (avg_heat * 0.4 + math.sqrt(variance) * 0.6) * dopamine_level

    return max(0.0, min(1.0, raw_priority))


# Backward compatibility alias
compute_sequence_rpe = compute_sequence_priority


# ── Sequence Selection ───────────────────────────────────────────────────


def select_replay_sequences(
    candidate_sequences: list[ReplaySequence],
    max_sequences: int = _MAX_SEQUENCES_PER_SWR,
    priority_threshold: float = _PRIORITY_THRESHOLD,
) -> list[ReplaySequence]:
    """Select top replay sequences for an SWR burst.

    Filters by priority threshold, then ranks by priority score. Ensures
    at least one forward and one reverse sequence if available.
    """
    viable = [
        s for s in candidate_sequences if s.priority_score >= priority_threshold
    ]

    if not viable:
        return _fallback_selection(candidate_sequences, max_sequences)

    return _balanced_selection(viable, max_sequences)


def _fallback_selection(
    candidates: list[ReplaySequence],
    max_sequences: int,
) -> list[ReplaySequence]:
    """Take top candidates when none meet the priority threshold."""
    by_priority = sorted(
        candidates, key=lambda s: s.priority_score, reverse=True
    )
    return by_priority[:max_sequences]


def _balanced_selection(
    viable: list[ReplaySequence],
    max_sequences: int,
) -> list[ReplaySequence]:
    """Select sequences ensuring both forward and reverse are represented."""
    forward = sorted(
        [s for s in viable if s.direction == ReplayDirection.FORWARD],
        key=lambda s: s.priority_score,
        reverse=True,
    )
    reverse = sorted(
        [s for s in viable if s.direction == ReplayDirection.REVERSE],
        key=lambda s: s.priority_score,
        reverse=True,
    )

    selected: list[ReplaySequence] = []
    if forward:
        selected.append(forward[0])
    if reverse:
        selected.append(reverse[0])

    all_sorted = sorted(viable, key=lambda s: s.priority_score, reverse=True)
    for seq in all_sorted:
        if len(selected) >= max_sequences:
            break
        if seq not in selected:
            selected.append(seq)

    return selected[:max_sequences]
