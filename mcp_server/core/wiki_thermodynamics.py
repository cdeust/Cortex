"""Phase 4 — Wiki page thermodynamics.

Pages live in an ecology, not a library: they earn existence through
citation and access, lose it through idleness, staleness, and
redundancy. This module is the pure-logic layer that decides:

  - how much heat a page decays per tick
  - when a page transitions between lifecycle_states
  - when a page gets archived

Same physics as pg_store memory decay, with lifecycle-aware half-lives:

  active     half-life 30d   — current cognitive territory
  area       half-life 90d   — ongoing reference, touched occasionally
  archived   no decay        — already at floor
  evergreen  no decay        — protected (cross-domain knowledge)

Pure logic — no I/O. The handler reads pages, calls these helpers,
writes back the new (heat, lifecycle_state, is_stale, archived_at).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


# ── Tunable thresholds ────────────────────────────────────────────────

HALF_LIFE_DAYS: dict[str, float] = {
    "active": 30.0,
    "area": 90.0,
    "archived": math.inf,  # no further decay
    "evergreen": math.inf,  # never decays
}

# Lifecycle transition thresholds
ACTIVE_TO_AREA_HEAT = 0.3
ACTIVE_TO_AREA_IDLE_DAYS = 14
AREA_TO_ARCHIVED_HEAT = 0.1
AREA_TO_ARCHIVED_IDLE_DAYS = 90
ARCHIVED_REVIVAL_HEAT = 0.4  # re-promote on citation bump above this
HEAT_FLOOR = 0.0


@dataclass(frozen=True)
class HeatDecision:
    """Per-page thermodynamic update plan."""

    page_id: int
    new_heat: float
    new_lifecycle: str
    transitioned: bool
    archived_at: datetime | None
    rationale: str


def _safe_dt(value) -> datetime:
    """Coerce a value to an aware UTC datetime (defaults to now)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return datetime.now(tz=timezone.utc)


def decay_heat(
    *,
    current_heat: float,
    last_tended: datetime,
    lifecycle_state: str,
    now: datetime | None = None,
) -> float:
    """Apply exponential decay since last_tended.

    heat = current_heat * exp(-ln(2) * elapsed_days / half_life_days)
    """
    half_life = HALF_LIFE_DAYS.get(lifecycle_state, 30.0)
    if math.isinf(half_life):
        return current_heat
    now = now or datetime.now(tz=timezone.utc)
    elapsed = (now - _safe_dt(last_tended)).total_seconds() / 86400.0
    if elapsed <= 0:
        return current_heat
    decayed = current_heat * math.exp(-math.log(2) * elapsed / half_life)
    return max(HEAT_FLOOR, decayed)


def transition_lifecycle(
    *,
    current_state: str,
    heat_after_decay: float,
    last_tended: datetime,
    now: datetime | None = None,
) -> tuple[str, bool, str]:
    """Decide whether to move to a new lifecycle state.

    Returns (new_state, transitioned, rationale).
    """
    if current_state == "evergreen":
        return ("evergreen", False, "evergreen — never auto-transitions")

    now = now or datetime.now(tz=timezone.utc)
    elapsed_days = (now - _safe_dt(last_tended)).total_seconds() / 86400.0

    if current_state == "active":
        if (
            heat_after_decay < ACTIVE_TO_AREA_HEAT
            and elapsed_days > ACTIVE_TO_AREA_IDLE_DAYS
        ):
            return (
                "area",
                True,
                f"heat={heat_after_decay:.2f} < {ACTIVE_TO_AREA_HEAT} "
                f"and idle {elapsed_days:.0f}d > {ACTIVE_TO_AREA_IDLE_DAYS}d",
            )
        return ("active", False, "active — within thresholds")

    if current_state == "area":
        if (
            heat_after_decay < AREA_TO_ARCHIVED_HEAT
            and elapsed_days > AREA_TO_ARCHIVED_IDLE_DAYS
        ):
            return (
                "archived",
                True,
                f"heat={heat_after_decay:.2f} < {AREA_TO_ARCHIVED_HEAT} "
                f"and idle {elapsed_days:.0f}d > {AREA_TO_ARCHIVED_IDLE_DAYS}d",
            )
        return ("area", False, "area — within thresholds")

    if current_state == "archived":
        # Revival happens via citation trigger (bumps heat directly);
        # if heat already crossed the threshold we re-promote.
        if heat_after_decay >= ARCHIVED_REVIVAL_HEAT:
            return (
                "active",
                True,
                f"heat={heat_after_decay:.2f} ≥ {ARCHIVED_REVIVAL_HEAT} "
                f"— revived from archive",
            )
        return ("archived", False, "archived — heat below revival threshold")

    return (current_state, False, f"unknown state: {current_state}")


def evaluate_page(page: dict, *, now: datetime | None = None) -> HeatDecision:
    """Run decay + transition for one page row.

    Inputs: dict with at least id, heat, lifecycle_state, tended.
    Returns the planned new state.
    """
    now = now or datetime.now(tz=timezone.utc)
    pid = int(page["id"])
    current_heat = float(page.get("heat", 1.0) or 0.0)
    current_state = page.get("lifecycle_state") or "active"
    last_tended = page.get("tended") or now

    new_heat = decay_heat(
        current_heat=current_heat,
        last_tended=last_tended,
        lifecycle_state=current_state,
        now=now,
    )
    new_state, transitioned, rationale = transition_lifecycle(
        current_state=current_state,
        heat_after_decay=new_heat,
        last_tended=last_tended,
        now=now,
    )

    archived_at = None
    if transitioned and new_state == "archived":
        archived_at = now

    return HeatDecision(
        page_id=pid,
        new_heat=new_heat,
        new_lifecycle=new_state,
        transitioned=transitioned,
        archived_at=archived_at,
        rationale=rationale,
    )


# ── Page-level metrics for the consolidate sweep ──────────────────────


@dataclass(frozen=True)
class ThermoStats:
    pages_evaluated: int
    pages_decayed: int
    transitions: dict[str, int]  # e.g. {"active->area": 3, "area->archived": 1}
    heat_floor_count: int  # how many landed at HEAT_FLOOR
    avg_heat_before: float
    avg_heat_after: float


def summarise(
    decisions: list[HeatDecision], original_heats: dict[int, float]
) -> ThermoStats:
    """Aggregate stats over a batch of HeatDecisions."""
    if not decisions:
        return ThermoStats(0, 0, {}, 0, 0.0, 0.0)
    transitions: dict[str, int] = {}
    decayed = 0
    floor = 0
    sum_before = 0.0
    sum_after = 0.0
    for d in decisions:
        before = original_heats.get(d.page_id, 0.0)
        sum_before += before
        sum_after += d.new_heat
        if d.new_heat < before - 1e-6:
            decayed += 1
        if d.new_heat <= HEAT_FLOOR + 1e-6:
            floor += 1
        if d.transitioned:
            # Build label like "active->area" — caller supplies prior state
            # via original_heats? No — we only have new_lifecycle here.
            # Use just the destination state for simplicity.
            label = f"->{d.new_lifecycle}"
            transitions[label] = transitions.get(label, 0) + 1
    return ThermoStats(
        pages_evaluated=len(decisions),
        pages_decayed=decayed,
        transitions=transitions,
        heat_floor_count=floor,
        avg_heat_before=sum_before / len(decisions),
        avg_heat_after=sum_after / len(decisions),
    )


__all__ = [
    "HALF_LIFE_DAYS",
    "ACTIVE_TO_AREA_HEAT",
    "ACTIVE_TO_AREA_IDLE_DAYS",
    "AREA_TO_ARCHIVED_HEAT",
    "AREA_TO_ARCHIVED_IDLE_DAYS",
    "HeatDecision",
    "ThermoStats",
    "decay_heat",
    "transition_lifecycle",
    "evaluate_page",
    "summarise",
    # re-exported so tests don't need a separate import
    "timedelta",
]
