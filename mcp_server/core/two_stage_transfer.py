"""Two-stage transfer — hippocampal-cortical transfer delta and interleaving.

Extracted from two_stage_model.py to keep each module under 300 lines.
Handles the McClelland et al. (1995) transfer computation and interleaved
replay scheduling.

References:
    McClelland JL, McNaughton BL, O'Reilly RC (1995) Why there are
        complementary learning systems. Psychol Rev 102:419-457
    Ketz NA, et al. (2023) C-HORSE: A computational model of hippocampal-
        cortical complementary learning. eLife 12:e77185
        Hippocampal LR = 0.02, cortical LR = 0.002 (10:1 ratio)
    Tse D, et al. (2007) Schemas and memory consolidation. Science 316:76-82
        Schema-consistent memories consolidate 15x faster (30 days -> 48h)

Pure business logic — no I/O.
"""

from __future__ import annotations

import math

# ── Configuration ─────────────────────────────────────────────────────────

# Cortical learning rate from C-HORSE model (Ketz et al., eLife 12:e77185, 2023).
# C-HORSE specifies hippocampal LR = 0.02 and cortical LR = 0.002 (10:1 ratio).
# We use the cortical rate here because this constant governs cortical trace
# strengthening during replay-driven transfer.
_REPLAY_TRANSFER_RATE = 0.02

# Schema-accelerated transfer multiplier for schema-consistent memories.
# Tse et al. (2007) showed 15x acceleration in rats (30 days -> 48 hours).
# Engineering adaptation: our system operates at hours/days timescale (not weeks),
# so we compress the 15x biological factor to 2.5x. This preserves the qualitative
# effect (schema-consistent memories transfer faster) while fitting the compressed
# timescale of an AI memory system.
_SCHEMA_ACCELERATION = 2.5

# Engineering choice: minimum replays before transfer begins. No direct paper
# source; reflects the intuition that a single replay is insufficient to
# establish a cortical trace.
_MIN_REPLAYS_FOR_TRANSFER = 2

# Hippocampal release threshold: below this, hippocampal trace can be freed.
# Engineering choice calibrated to the transfer rate above.
_HIPPOCAMPAL_RELEASE_THRESHOLD = 0.05


# ── Transfer Computation ─────────────────────────────────────────────────


def compute_transfer_delta(
    current_dependency: float,
    replay_count: int,
    schema_match: float = 0.0,
    importance: float = 0.5,
    *,
    transfer_rate: float = _REPLAY_TRANSFER_RATE,
    schema_acceleration: float = _SCHEMA_ACCELERATION,
    min_replays: int = _MIN_REPLAYS_FOR_TRANSFER,
) -> float:
    """Compute how much hippocampal dependency decreases from one replay event.

    Each SWR replay strengthens the cortical trace and weakens hippocampal
    dependency. The base rate is the cortical learning rate from C-HORSE
    (Ketz et al., 2023, eLife 12:e77185). Schema consistency accelerates
    transfer per Tse et al. (2007), adapted to compressed timescale.

    Args:
        current_dependency: Current hippocampal dependency [0, 1].
        replay_count: Total replays so far (including this one).
        schema_match: Schema match score [0, 1].
        importance: Memory importance [0, 1].
        transfer_rate: Base cortical learning rate per replay (default: 0.02).
        schema_acceleration: Schema-consistent speedup factor (default: 2.5).
        min_replays: Minimum replays before any transfer begins.

    Returns:
        Delta to subtract from hippocampal_dependency (always >= 0).
    """
    if replay_count < min_replays:
        return 0.0

    if current_dependency <= _HIPPOCAMPAL_RELEASE_THRESHOLD:
        return 0.0

    base = _compute_base_rate(replay_count, min_replays, transfer_rate)
    schema_factor = 1.0 + schema_match * (schema_acceleration - 1.0)
    importance_factor = 0.8 + importance * 0.4

    delta = base * schema_factor * importance_factor
    return min(delta, current_dependency)


def _compute_base_rate(
    replay_count: int,
    min_replays: int,
    transfer_rate: float,
) -> float:
    """Compute base transfer rate with diminishing returns.

    Early replays matter most; later ones have diminishing impact.
    """
    effective_replays = replay_count - min_replays + 1
    return transfer_rate / math.sqrt(effective_replays)


def update_hippocampal_dependency(
    current_dependency: float,
    replay_count: int,
    schema_match: float = 0.0,
    importance: float = 0.5,
) -> float:
    """Update hippocampal dependency after a replay event.

    Returns the new dependency value.
    """
    delta = compute_transfer_delta(
        current_dependency,
        replay_count,
        schema_match,
        importance,
    )
    return max(0.0, round(current_dependency - delta, 4))


# ── Interleaved Training ─────────────────────────────────────────────────


def compute_interleaving_schedule(
    candidates: list[dict],
) -> list[int]:
    """Generate an interleaved replay schedule from candidates.

    Interleaving prevents catastrophic interference in cortical learning.
    Rather than replaying all similar memories consecutively, we interleave
    memories from different clusters/domains.

    Args:
        candidates: Replay candidates with 'domain' and 'replay_priority'.

    Returns:
        List of candidate indices in interleaved order.
    """
    if len(candidates) <= 1:
        return list(range(len(candidates)))

    domain_groups = _group_by_domain(candidates)
    return _round_robin_schedule(domain_groups, len(candidates))


def _group_by_domain(candidates: list[dict]) -> dict[str, list[int]]:
    """Group candidate indices by their domain."""
    groups: dict[str, list[int]] = {}
    for i, c in enumerate(candidates):
        domain = c.get("domain", "default")
        groups.setdefault(domain, []).append(i)
    return groups


def _round_robin_schedule(
    domain_groups: dict[str, list[int]],
    total: int,
) -> list[int]:
    """Produce a round-robin interleaved schedule across domains."""
    schedule: list[int] = []
    domain_iters = {d: iter(indices) for d, indices in domain_groups.items()}
    domains = list(domain_groups.keys())

    while len(schedule) < total:
        progress = False
        for domain in domains:
            try:
                idx = next(domain_iters[domain])
                schedule.append(idx)
                progress = True
            except StopIteration:
                continue
        if not progress:
            break

    return schedule
