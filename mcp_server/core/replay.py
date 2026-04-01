"""Hippocampal replay — SWR-driven memory consolidation and context reconstruction.

Two modes of operation:

1. **Context restoration** (original): Format checkpoint + hot memories for
   post-compaction injection. This is the "macro-replay" after Claude Code context
   compaction.

2. **SWR replay** (new): During consolidation, generate replay sequences from
   memory traces ordered by temporal/causal chains. Forward replay projects
   sequences forward (what happened after X?). Reverse replay traces backward
   from outcomes to causes (what led to Y?). Replay-dependent plasticity updates
   edge weights via STDP.

SWR replay is gated by the oscillatory clock — replay only fires during
sharp-wave ripple events, not on every consolidation call. Replay prioritizes
sequences with high dopamine-modulated priority scores (see replay_selection.py).

Biological adaptation note:
    Biological SWR replay uses population burst dynamics where place cell
    sequences are reactivated in compressed time (Ecker et al. 2022, eLife).
    This code approximates replay by building sequences from entity-overlap
    and temporal ordering, not from population-level burst detection. The
    compression ratio (~20x, Davidson et al. 2009) is applied to STDP timing
    in replay_execution.py.

References:
    Foster DJ, Wilson MA (2006) Reverse replay of behavioural sequences
        in hippocampal place cells during the awake state. Nature 440:680-683
    Diba K, Buzsaki G (2007) Forward and reverse hippocampal place-cell
        sequences during ripples. Nature Neurosci 10:1241-1242
    Davidson TJ, Kloosterman F, Wilson MA (2009) Hippocampal replay of
        extended experience. Neuron 63:497-507
    Ecker A et al. (2022) Hippocampal sharp wave-ripples and the associated
        sequence replay emerge from structured synaptic interactions. eLife
    Nelli S et al. (2025) Large SWRs promote hippocampo-cortical reactivation.
        Neuron (in press)

This module is the public API. Implementation is split across:
    - replay_types.py — Data types (ReplayDirection, ReplayEvent, etc.)
    - replay_formatting.py — Context restoration and micro-checkpoint detection
    - replay_execution.py — Sequence building and STDP pair extraction
    - replay_selection.py — Priority scoring and sequence selection

Pure business logic — no I/O. Storage operations are handled by the caller.
"""

from __future__ import annotations

from mcp_server.core.replay_execution import (
    build_causal_sequence,
    build_temporal_sequence,
    compute_replay_stdp_pairs,
)
from mcp_server.core.replay_formatting import (
    format_restoration,
    should_micro_checkpoint,
)
from mcp_server.core.replay_selection import (
    compute_sequence_priority,
    compute_sequence_rpe,  # backward compat alias
    select_replay_sequences,
)
from mcp_server.core.replay_types import (
    ReplayDirection,
    ReplayEvent,
    ReplayResult,
    ReplaySequence,
)

# ── Constants ────────────────────────────────────────────────────────────

_MIN_SEQUENCE_LENGTH = 2
_MAX_SEQUENCES_PER_SWR = 5


# ── Full SWR Replay Cycle ────────────────────────────────────────────────


def _select_seeds(hot_memories: list[dict], max_sequences: int) -> list[dict]:
    """Select top seed memories by heat for replay."""
    seeds = sorted(hot_memories, key=lambda m: m.get("heat", 0), reverse=True)
    return seeds[: max_sequences * 2]


def run_swr_replay(
    hot_memories: list[dict],
    related_memories: list[dict],
    relationships: list[dict],
    *,
    dopamine_level: float = 1.0,
    swr_active: bool = True,
    max_sequences: int = _MAX_SEQUENCES_PER_SWR,
) -> ReplayResult:
    """Execute a full SWR replay cycle.

    This is the main entry point for replay during consolidation.
    Only runs if SWR is active (from oscillatory clock).
    """
    if not swr_active or not hot_memories:
        return ReplayResult()

    seeds = _select_seeds(hot_memories, max_sequences)
    candidates = _build_candidate_sequences(
        seeds, related_memories, relationships, dopamine_level
    )
    candidates.extend(_build_temporal_candidates(hot_memories, dopamine_level))

    selected = select_replay_sequences(candidates, max_sequences)
    return _aggregate_results(selected)


# ── Candidate Building ───────────────────────────────────────────────────


def _build_candidate_sequences(
    seeds: list[dict],
    related_memories: list[dict],
    relationships: list[dict],
    dopamine_level: float,
) -> list[ReplaySequence]:
    """Build forward and reverse causal sequences from seed memories."""
    candidates: list[ReplaySequence] = []

    for seed in seeds:
        for direction in (ReplayDirection.FORWARD, ReplayDirection.REVERSE):
            seq = _build_single_sequence(
                seed,
                related_memories,
                relationships,
                direction,
                dopamine_level,
            )
            if seq is not None:
                candidates.append(seq)

    return candidates


def _build_single_sequence(
    seed: dict,
    related_memories: list[dict],
    relationships: list[dict],
    direction: ReplayDirection,
    dopamine_level: float,
) -> ReplaySequence | None:
    """Build and score a single causal sequence, returning None if too short."""
    events = build_causal_sequence(seed, related_memories, relationships, direction)

    if len(events) < _MIN_SEQUENCE_LENGTH:
        return None

    rpe = compute_sequence_priority(events, dopamine_level)
    stdp = compute_replay_stdp_pairs(events, direction)

    return ReplaySequence(
        events=events,
        direction=direction,
        priority_score=rpe,
        stdp_pairs=stdp,
    )


def _build_temporal_candidates(
    hot_memories: list[dict],
    dopamine_level: float,
) -> list[ReplaySequence]:
    """Build purely temporal sequences (no causal filtering)."""
    events = build_temporal_sequence(hot_memories)

    if len(events) < _MIN_SEQUENCE_LENGTH:
        return []

    rpe = compute_sequence_priority(events, dopamine_level)
    stdp = compute_replay_stdp_pairs(events, ReplayDirection.FORWARD)

    return [
        ReplaySequence(
            events=events,
            direction=ReplayDirection.FORWARD,
            priority_score=rpe,
            stdp_pairs=stdp,
        )
    ]


# ── Result Aggregation ───────────────────────────────────────────────────


def _aggregate_results(selected: list[ReplaySequence]) -> ReplayResult:
    """Aggregate selected sequences into a ReplayResult."""
    result = ReplayResult()
    all_stdp: list[tuple[int, int, float]] = []
    schema_signals: list[dict] = []
    memory_ids: set[int] = set()

    for seq in selected:
        all_stdp.extend(seq.stdp_pairs)
        memory_ids.update(e.memory_id for e in seq.events)

        if seq.direction == ReplayDirection.FORWARD:
            result.forward_count += 1
        else:
            result.reverse_count += 1

        if seq.priority_score > 0.5:
            schema_signals.append(
                {
                    "entities": [e for ev in seq.events for e in ev.entities],
                    "priority": seq.priority_score,
                    "direction": seq.direction.value,
                    "update_strength": seq.priority_score * 0.3,
                }
            )

    result.sequences_generated = len(selected)
    result.memories_replayed = len(memory_ids)
    result.stdp_updates = all_stdp
    result.schema_signals = schema_signals

    return result


# ── Replay Diagnostics ───────────────────────────────────────────────────


def describe_replay_result(result: ReplayResult) -> dict:
    """Human-readable summary of replay cycle."""
    return {
        "sequences_generated": result.sequences_generated,
        "memories_replayed": result.memories_replayed,
        "forward_sequences": result.forward_count,
        "reverse_sequences": result.reverse_count,
        "stdp_updates_count": len(result.stdp_updates),
        "schema_signals_count": len(result.schema_signals),
    }


# ── Public API ───────────────────────────────────────────────────────────
# Public API
# `mcp_server.core.replay` continue to work unchanged.

__all__ = [
    # Formatting
    "should_micro_checkpoint",
    "format_restoration",
    # Types
    "ReplayDirection",
    "ReplayEvent",
    "ReplaySequence",
    "ReplayResult",
    # Execution
    "build_temporal_sequence",
    "build_causal_sequence",
    "compute_replay_stdp_pairs",
    # Selection
    "compute_sequence_priority",
    "compute_sequence_rpe",  # backward compat alias
    "select_replay_sequences",
    # Orchestration
    "run_swr_replay",
    "describe_replay_result",
]
