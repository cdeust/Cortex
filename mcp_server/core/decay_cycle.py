"""Decay cycle — periodic heat decay with consolidation-dependent permastore.

Two decay models, both gated by consolidation stage and permastore floor:

1. Exponential (default): heat(t) = heat(0) * lambda^t  (Ebbinghaus 1885).
   Decay rate is stage-adjusted via cascade_stages.compute_stage_adjusted_decay():
   LABILE decays 2x faster, CONSOLIDATED decays 2x slower.

2. ACT-R base-level activation (adaptive_decay=True):
   Anderson JR, Lebiere C (1998) "The Atomic Components of Thought", Eq. 4.4.
   B_i = ln(n) - d * ln(L)  where n=accesses, L=lifetime, d=0.5.

Both paths enforce a consolidation-dependent heat floor (permastore):
  - LABILE, EARLY_LTP: floor = 0.0 (can decay to zero)
  - LATE_LTP: floor = 0.05 (partial structural support)
  - CONSOLIDATED: floor = 0.10 (permanent — Bahrick 1984, Kandel 2001)
  - RECONSOLIDATING: floor = 0.05 (was consolidated, temporarily labile)

The permastore mechanism is grounded in:
  - Bahrick HP (1984) "Semantic memory content in permastore" —
    30-year retention plateau without rehearsal.
  - Kandel ER (2001) "Molecular biology of memory storage" —
    at 72h post-encoding, structural synaptic changes are permanent.
  - Benna MK & Fusi S (2016) "Computational principles of synaptic memory
    consolidation" — cascade models produce non-zero retention floors.

Pure business logic — receives memory data, returns updated heat values.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from mcp_server.core.cascade_stages import (
    compute_stage_adjusted_decay,
    get_heat_floor,
)
from mcp_server.core.thermodynamics import compute_decay

# -- ACT-R Constants (Anderson & Lebiere 1998) ---------------------------------

# d: base decay parameter. Standard ACT-R value is 0.5.
_ACT_R_DECAY_D: float = 0.5

# s: noise parameter for activation → probability mapping.
# Standard ACT-R uses s ≈ 0.4. We use 1.0 for our hours timescale.
_ACT_R_NOISE_S: float = 1.0

# Minimum hours to avoid log(0)
_MIN_LIFETIME_HOURS: float = 0.01


def _parse_datetime(value) -> datetime | None:
    """Parse a datetime from either a string or native datetime object.

    psycopg3 returns native datetime objects from TIMESTAMPTZ columns,
    while some code paths pass ISO strings. Handle both.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


def _hours_since_access(mem: dict, now: datetime) -> float | None:
    """Return hours elapsed since last access, or None if unparseable.

    Fallback chain: last_accessed → ingested_at → created_at. The
    ingested_at fallback (added for the consolidation-cadence fix —
    tasks/e1-v3-locomo-smoke-finding.md) ensures backfilled memories
    with a backdated created_at do not falsely register as
    "last-accessed years ago" when last_accessed is missing.
    """
    last_accessed = (
        mem.get("last_accessed")
        or mem.get("ingested_at")
        or mem.get("created_at", "")
    )
    last_dt = _parse_datetime(last_accessed)
    if last_dt is None:
        return None
    hours = (now - last_dt).total_seconds() / 3600.0
    return hours if hours > 0 else None


def _hours_since_creation(mem: dict, now: datetime) -> float | None:
    """Return hours elapsed since the memory entered THIS system.

    ACT-R "lifetime L" in B_i = ln(n) − d·ln(L) is lifetime in the
    learner's system since acquisition (Anderson & Lebiere 1998), not
    elapsed time since the original-source event. For Cortex this is
    ``ingested_at``: backfilled / imported memories with backdated
    ``created_at`` would otherwise return a wrongly-large L on first
    decay pass and collapse heat to near-zero before any access.
    Source: tasks/e1-v3-locomo-smoke-finding.md.

    Falls back to ``created_at`` only for in-memory dicts that never
    round-tripped through PG (schema backfills ingested_at=created_at
    for legacy rows, so PG-sourced dicts always have the field).
    """
    raw = mem.get("ingested_at") or mem.get("created_at", "")
    ingested_dt = _parse_datetime(raw)
    if ingested_dt is None:
        return None
    hours = (now - ingested_dt).total_seconds() / 3600.0
    return max(_MIN_LIFETIME_HOURS, hours)


def compute_actr_base_level(
    access_count: int,
    lifetime_hours: float,
    d: float = _ACT_R_DECAY_D,
) -> float:
    """ACT-R base-level activation (Anderson & Lebiere 1998, Eq. 4.4).

    B_i = ln(sum_j(t_j^{-d}))

    Approximation assuming uniformly spaced accesses over lifetime:
    B_i ≈ ln(n) - d * ln(L)

    where n = access_count (minimum 1), L = lifetime in hours.

    Returns raw activation (can be negative = below retrieval threshold).
    """
    n = max(1, access_count)
    L = max(_MIN_LIFETIME_HOURS, lifetime_hours)
    return math.log(n) - d * math.log(L)


def actr_activation_to_heat(
    base_level: float,
    s: float = _ACT_R_NOISE_S,
) -> float:
    """Map ACT-R base-level activation to heat [0, 1] via logistic.

    P(recall) = 1 / (1 + exp(-B_i / s))  (Anderson & Lebiere 1998, Eq. 4.5)

    This is the standard ACT-R retrieval probability equation.
    """
    return 1.0 / (1.0 + math.exp(-base_level / s))


def _compute_actr_decay(
    mem: dict,
    now: datetime,
    importance: float = 0.5,
    valence: float = 0.0,
) -> float | None:
    """Compute heat via ACT-R base-level activation.

    Importance and valence modulate d (decay rate):
    - High importance (>0.7): d reduced by 20% (slower decay)
    - High |valence|: d reduced proportionally (emotional resistance)

    These modulations follow the general finding that meaningful and
    emotional memories decay slower (McGaugh 2004), adapted to the
    ACT-R framework.
    """
    lifetime = _hours_since_creation(mem, now)
    if lifetime is None:
        return None

    access_count = mem.get("access_count", 1)

    # Modulate d based on importance and emotion
    d = _ACT_R_DECAY_D
    if importance > 0.7:
        d *= 0.8  # Important memories decay 20% slower
    d *= 1.0 - abs(valence) * 0.3  # Emotional memories resist decay
    d = max(0.1, d)  # Floor to prevent d=0

    base_level = compute_actr_base_level(access_count, lifetime, d)
    return actr_activation_to_heat(base_level)


def _compute_single_decay(
    mem: dict,
    now: datetime,
    decay_factor: float,
    importance_decay_factor: float,
    emotional_decay_resistance: float,
    adaptive_decay: bool = False,
) -> tuple[int, float] | None:
    """Compute decay for a single memory. Returns (id, new_heat) or None.

    Incorporates two critical mechanisms:
    1. Stage-adjusted decay rate (Kandel 2001): consolidated memories
       decay slower via compute_stage_adjusted_decay().
    2. Heat floor / permastore (Bahrick 1984, Benna & Fusi 2016):
       consolidated memories never decay below their stage's heat_floor.
    """
    current_heat = mem.get("heat", 0.0)
    stage = mem.get("consolidation_stage", "labile")

    # Permastore floor: consolidated memories are always retrievable
    floor = get_heat_floor(stage)

    if adaptive_decay:
        # ACT-R path: compute heat from base-level activation
        new_heat = _compute_actr_decay(
            mem,
            now,
            importance=mem.get("importance", 0.5),
            valence=mem.get("emotional_valence", 0.0),
        )
        if new_heat is None:
            return None
        new_heat = min(current_heat, new_heat)
    else:
        # Ebbinghaus exponential path with stage-adjusted rate
        hours = _hours_since_access(mem, now)
        if hours is None:
            return None

        # Apply consolidation stage multiplier (Kandel 2001)
        adj_decay = compute_stage_adjusted_decay(decay_factor, stage)
        adj_imp_decay = compute_stage_adjusted_decay(importance_decay_factor, stage)

        new_heat = compute_decay(
            current_heat,
            hours,
            importance=mem.get("importance", 0.5),
            valence=mem.get("emotional_valence", 0.0),
            confidence=mem.get("confidence", 1.0),
            decay_factor=adj_decay,
            importance_decay_factor=adj_imp_decay,
            emotional_decay_resistance=emotional_decay_resistance,
        )

    # Enforce permastore floor (Bahrick 1984)
    new_heat = max(floor, new_heat)

    if abs(new_heat - current_heat) > 0.001:
        return (mem["id"], round(new_heat, 6))
    return None


def compute_decay_updates(
    memories: list[dict],
    now: datetime | None = None,
    *,
    decay_factor: float = 0.95,
    importance_decay_factor: float = 0.998,
    emotional_decay_resistance: float = 0.5,
    cold_threshold: float = 0.05,
    adaptive_decay: bool = False,
) -> list[tuple[int, float]]:
    """Compute new heat values for all memories.

    Returns list of (memory_id, new_heat) tuples for memories that changed.
    Skips protected memories and already-cold memories.

    When adaptive_decay=True, uses ACT-R base-level activation
    (Anderson & Lebiere 1998) instead of exponential forgetting.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    updates: list[tuple[int, float]] = []
    for mem in memories:
        if mem.get("is_protected") or mem.get("heat", 0.0) < cold_threshold:
            continue
        result = _compute_single_decay(
            mem,
            now,
            decay_factor,
            importance_decay_factor,
            emotional_decay_resistance,
            adaptive_decay=adaptive_decay,
        )
        if result is not None:
            updates.append(result)

    return updates


def _parse_hours_since_access(record: dict, now: datetime) -> float | None:
    """Parse hours since last access from a memory or entity record.

    Fallback chain mirrors _hours_since_access: last_accessed →
    ingested_at → created_at. Entities do not currently carry
    ingested_at, so this is a no-op for entity records but defensive
    for memory dicts that take this path.
    """
    last_accessed = (
        record.get("last_accessed")
        or record.get("ingested_at")
        or record.get("created_at", "")
    )
    last_dt = _parse_datetime(last_accessed)
    if last_dt is None:
        return None
    hours = (now - last_dt).total_seconds() / 3600.0
    return hours if hours > 0 else None


def compute_entity_decay(
    entities: list[dict],
    now: datetime | None = None,
    *,
    decay_factor: float = 0.98,
    cold_threshold: float = 0.05,
) -> list[tuple[int, float]]:
    """Compute new heat values for entities.

    Entities use exponential decay (simpler — no access history tracked).
    Returns list of (entity_id, new_heat) tuples.
    """
    if now is None:
        now = datetime.now(timezone.utc)

    updates: list[tuple[int, float]] = []
    for entity in entities:
        current_heat = entity.get("heat", 0.0)
        if current_heat < cold_threshold:
            continue
        hours = _parse_hours_since_access(entity, now)
        if hours is None:
            continue
        new_heat = current_heat * (decay_factor**hours)
        if abs(new_heat - current_heat) > 0.001:
            updates.append((entity["id"], round(new_heat, 6)))

    return updates
