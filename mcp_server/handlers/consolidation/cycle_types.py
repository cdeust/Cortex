"""Cycle execution/telemetry data types for the headless authoring worker.

No import-cycle concern here: these are plain dataclasses with no
dependency on ``headless_authoring`` or any sibling.

source: ADR-0354"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class CycleBudget:
    """Per-cycle wall-clock + USD budget tracker.

        Pre-condition:  ``deadline`` is a ``time.monotonic()`` value in the
                        future; ``usd_cap`` is a float (<=0 means unlimited).
        Invariant:      ``usd_spent`` is monotonically non-decreasing.

        Concurrency note: with CORTEX_HEADLESS_CONCURRENCY > 1, multiple
        coroutines can see ``exhausted() == False`` simultaneously before any
        of them has charged the budget.  The USD cap is therefore a SOFT
        ceiling with overshoot of at most ``concurrency - 1`` calls beyond
        the cap.  This is acceptable for an operational safety rail.

    source: ADR-0354"""

    deadline: float  # time.monotonic() timestamp
    usd_cap: float  # <=0 means no USD cap
    usd_spent: float = field(default=0.0)
    # Calls whose cost the CLI did not report: usd_spent excludes them, so
    # usd_spent is a lower bound whenever this is > 0 (#733).
    unpriced_calls: int = field(default=0)


def cycle_budget_time_left(budget: "CycleBudget") -> float:
    """Remaining seconds until deadline (negative when expired)."""
    return budget.deadline - time.monotonic()


def cycle_budget_exhausted(budget: "CycleBudget") -> bool:
    """True when wall-clock time is up OR the USD cap is reached."""
    if cycle_budget_time_left(budget) <= 0:
        return True
    return budget.usd_cap > 0 and budget.usd_spent >= budget.usd_cap


def cycle_budget_charge(budget: "CycleBudget", usd: float | None) -> None:
    """Add ``usd`` to the running spend, or count the call as unpriced.

    Pre-condition:  ``usd`` is None (cost not reported) or >= 0.
    Post-condition: ``budget.usd_spent`` incremented by ``usd``, or
                    ``budget.unpriced_calls`` incremented by 1 when None.
    """
    if usd is None:
        budget.unpriced_calls += 1
        return
    budget.usd_spent += usd


@dataclass
class DrainResult:
    """One drain attempt's outcome."""

    page_path: str
    gap: str
    status: str  # "filled" | "failed" | "skipped"
    duration_ms: int
    detail: str = ""


@dataclass
class CycleSummary:
    """Per-invocation roll-up with budget telemetry."""

    pages_scanned: int
    pages_with_gaps: int
    drains_attempted: int
    drains_filled: int
    drains_failed: int
    duration_ms: int
    results: list[DrainResult]
    # source: ADR-0354
    usd_spent: float = 0.0
    # source: ADR-0354
    wall_clock_ms: int = 0
    skipped_budget: int = 0
    # source: #733 — calls absent from usd_spent because no cost was reported
    unpriced_calls: int = 0
