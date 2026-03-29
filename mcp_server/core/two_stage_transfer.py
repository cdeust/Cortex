"""Two-stage transfer — hippocampal-cortical transfer delta and interleaving.

Extracted from two_stage_model.py to keep each module under 300 lines.
Handles the McClelland et al. (1995) transfer computation and interleaved
replay scheduling.

Pure business logic — no I/O.
"""

from __future__ import annotations

import math

# ── Configuration ─────────────────────────────────────────────────────────

# Replay effectiveness: how much each SWR replay reduces hippocampal dependency
_REPLAY_TRANSFER_RATE = 0.08

# Schema-accelerated transfer: multiplier on transfer rate for schema-consistent memories
_SCHEMA_ACCELERATION = 2.5

# Minimum replays needed before any transfer begins
_MIN_REPLAYS_FOR_TRANSFER = 2

# Hippocampal release threshold: below this, hippocampal trace can be freed
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
    dependency. The rate is accelerated by schema consistency and modulated
    by importance.

    Args:
        current_dependency: Current hippocampal dependency [0, 1].
        replay_count: Total replays so far (including this one).
        schema_match: Schema match score [0, 1].
        importance: Memory importance [0, 1].
        transfer_rate: Base transfer rate per replay.
        schema_acceleration: How much schema match speeds up transfer.
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
