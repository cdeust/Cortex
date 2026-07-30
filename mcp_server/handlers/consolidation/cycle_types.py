"""Cycle execution/telemetry data types for the headless authoring worker.

Split out of ``headless_authoring`` (Fowler: Move Function, issue #276)
to keep that module under the size limit; ``InvokeResult`` and
``_AnchorCandidate`` stay there (worker identity/config, a distinct
concern from a cycle's execution telemetry). The public import surface
stays ``headless_authoring``, which re-exports all three names below —
every existing ``_root.CycleBudget`` / ``_root.DrainResult`` /
``_root.CycleSummary`` call site is unaffected: same class objects,
same module attribute, just defined in a different file.

No import-cycle concern here: these are plain dataclasses with no
dependency on ``headless_authoring`` or any sibling.
"""

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

    Data only — deliberately no methods. mutmut's mutation generator
    categorically excludes the body of any `@dataclass`-decorated class
    (`mutmut/mutation/file_mutation.py:236`), so logic placed on methods
    here would carry zero mutation coverage no matter how the test loader
    names the module (issue #262 3rd pass; issue #282).
    `cycle_budget_time_left` / `cycle_budget_exhausted` /
    `cycle_budget_charge` below carry the same logic as free functions
    instead.
    """

    deadline: float  # time.monotonic() timestamp
    usd_cap: float  # <=0 means no USD cap
    usd_spent: float = field(default=0.0)


def cycle_budget_time_left(budget: "CycleBudget") -> float:
    """Remaining seconds until deadline (negative when expired)."""
    return budget.deadline - time.monotonic()


def cycle_budget_exhausted(budget: "CycleBudget") -> bool:
    """True when wall-clock time is up OR the USD cap is reached."""
    if cycle_budget_time_left(budget) <= 0:
        return True
    return budget.usd_cap > 0 and budget.usd_spent >= budget.usd_cap


def cycle_budget_charge(budget: "CycleBudget", usd: float) -> None:
    """Add ``usd`` to the running spend.

    Pre-condition:  ``usd`` >= 0.
    Post-condition: ``budget.usd_spent`` incremented by ``usd``.
    """
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
    # Budget telemetry fields (added in throttle refactor — callers that
    # access only the original fields are not affected).
    usd_spent: float = 0.0
    # wall_clock_ms is intentionally equal to duration_ms for the cycle: both
    # measure the cycle's wall-clock span. Kept as a distinct, explicitly-named
    # field because wiki_maintenance's telemetry dict emits both keys; the
    # original duration_ms is retained for pre-throttle callers.
    wall_clock_ms: int = 0
    skipped_budget: int = 0
