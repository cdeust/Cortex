"""Replay sequence selection and priority scoring.

Selects which replay sequences fire during an SWR burst based on
reward prediction error (RPE). Higher RPE sequences are prioritized
following Schultz (1997): dopamine signals select which experiences
to replay.

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

_RPE_THRESHOLD = 0.3
_MAX_SEQUENCES_PER_SWR = 5


# ── RPE Scoring ──────────────────────────────────────────────────────────


def compute_sequence_rpe(
    events: list[ReplayEvent],
    dopamine_level: float = 1.0,
) -> float:
    """Compute reward prediction error score for a replay sequence.

    Factors:
    - Average heat of memories (importance proxy)
    - Heat variance (surprising transitions = high RPE)
    - DA modulation (high DA amplifies all RPE)

    Returns:
        RPE score in [0, 1].
    """
    if len(events) < 2:
        return 0.0

    heats = [e.heat for e in events]
    avg_heat = sum(heats) / len(heats)
    variance = sum((h - avg_heat) ** 2 for h in heats) / len(heats)
    raw_rpe = (avg_heat * 0.4 + math.sqrt(variance) * 0.6) * dopamine_level

    return max(0.0, min(1.0, raw_rpe))


# ── Sequence Selection ───────────────────────────────────────────────────


def select_replay_sequences(
    candidate_sequences: list[ReplaySequence],
    max_sequences: int = _MAX_SEQUENCES_PER_SWR,
    rpe_threshold: float = _RPE_THRESHOLD,
) -> list[ReplaySequence]:
    """Select top replay sequences for an SWR burst.

    Filters by RPE threshold, then ranks by RPE score. Ensures at least
    one forward and one reverse sequence if available.
    """
    viable = [s for s in candidate_sequences if s.rpe_score >= rpe_threshold]

    if not viable:
        return _fallback_selection(candidate_sequences, max_sequences)

    return _balanced_selection(viable, max_sequences)


def _fallback_selection(
    candidates: list[ReplaySequence],
    max_sequences: int,
) -> list[ReplaySequence]:
    """Take top candidates when none meet the RPE threshold."""
    by_rpe = sorted(candidates, key=lambda s: s.rpe_score, reverse=True)
    return by_rpe[:max_sequences]


def _balanced_selection(
    viable: list[ReplaySequence],
    max_sequences: int,
) -> list[ReplaySequence]:
    """Select sequences ensuring both forward and reverse are represented."""
    forward = sorted(
        [s for s in viable if s.direction == ReplayDirection.FORWARD],
        key=lambda s: s.rpe_score,
        reverse=True,
    )
    reverse = sorted(
        [s for s in viable if s.direction == ReplayDirection.REVERSE],
        key=lambda s: s.rpe_score,
        reverse=True,
    )

    selected: list[ReplaySequence] = []
    if forward:
        selected.append(forward[0])
    if reverse:
        selected.append(reverse[0])

    all_sorted = sorted(viable, key=lambda s: s.rpe_score, reverse=True)
    for seq in all_sorted:
        if len(selected) >= max_sequences:
            break
        if seq not in selected:
            selected.append(seq)

    return selected[:max_sequences]
