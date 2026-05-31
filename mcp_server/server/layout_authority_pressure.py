"""Producer-feedback Act-channel for the layout authority.

The build worker (producer) and the layout authority (consumer) live in
different threads. The authority emits counters when it sheds work
(``_event_log_drops``, ``_edges_dropped``, growing pending-* buffers)
but those counters are diagnostic only — no caller reads them, no
producer consults them, no test asserts them.

Cochrane Finding A from ``tasks/layout-authority/audits/cochrane.md``
(≥48 of 52 audits converge on this): the loop is OPEN. The producer
fills P4 in ~64 ms; the detection loop is ~1000 ms; the tempo ratio is
~15× against the authority. Recommended fix (Boyd schwerpunkt,
unanimous mechanism across queueing/control/governance disciplines):
a single ``threading.Event`` set by the authority when any pressure
metric crosses a trip threshold and cleared when ALL metrics fall
below a lower clear threshold. The producer consults the Event
between batches at zero contention (Event.is_set is lock-free).

Hysteresis (high trip vs lower clear) is load-bearing: a single
threshold would flap as the deque length wobbles around it,
producing chatter rather than a useful signal.

source: Maxwell, J. C. (1868). "On Governors." Proc. Roy. Soc. 16,
270–283 — the foundational treatment of feedback stability via
threshold separation. Boyd, J. (1976). "Destruction and Creation."
— the OODA "Act" channel as the only thing that closes a loop. Beer,
S. (1972). *Brain of the Firm*, chapter on the S2/S1 channel.

Concurrency model:
    observe()       — called by the layout-authority producer thread.
                       Single-producer, no internal lock needed for
                       the metric snapshot; the Event itself is
                       thread-safe.
    is_overloaded() — called from ANY thread. Lock-free
                       (Event.is_set()).
    wait_for_clear  — called from ANY thread, typically the build
                       worker between batches. Bounded wait so a
                       genuinely stuck system cannot stall the build
                       forever.
    snapshot()      — diagnostic; reads atomic ints + Event flag.

The module is process-global (one log + one authority per process) to
keep the call sites unchanged from the integrator's pattern.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

# ── Tunables ─────────────────────────────────────────────────────────────
#
# Trip / clear thresholds are expressed as fractions of the consumer's
# bounded-capacity sentinels. They are intentionally far apart so the
# flag does not flap as the queue length wobbles by single events.
#
# source: Maxwell (1868) §3 — stability requires the upper and lower
# thresholds to bracket the system's natural oscillation amplitude.

_PENDING_EDGES_CAP = 100_000  # mirror of layout_authority._PENDING_EDGES_CAP
_PENDING_SYMBOLS_TOTAL_SOFT_CAP = 32_768  # rough multi-file aggregate

_TRIP_PENDING_EDGES = int(_PENDING_EDGES_CAP * 0.80)  # 80_000
_CLEAR_PENDING_EDGES = int(_PENDING_EDGES_CAP * 0.50)  # 50_000
_TRIP_PENDING_SYMBOLS = int(_PENDING_SYMBOLS_TOTAL_SOFT_CAP * 0.80)
_CLEAR_PENDING_SYMBOLS = int(_PENDING_SYMBOLS_TOTAL_SOFT_CAP * 0.50)


# ── State ────────────────────────────────────────────────────────────────


@dataclass
class _Snapshot:
    """Last-known metric values (single-producer, no lock needed)."""

    event_log_drops: int = 0
    edges_dropped: int = 0
    pending_edges: int = 0
    pending_symbols_total: int = 0
    # Previous drop counters so we can detect "a drop happened *this
    # observe*" rather than just absolute totals.
    last_log_drops: int = 0
    last_edges_dropped: int = 0


_state = _Snapshot()
_overloaded = threading.Event()


# ── Public API ───────────────────────────────────────────────────────────


def observe(
    *,
    event_log_drops: int,
    edges_dropped: int,
    pending_edges: int,
    pending_symbols_total: int,
) -> bool:
    """Update pressure state from a producer-side metric snapshot.

    Returns the new overload state (True iff the Event is set after
    this call). Single-producer precondition: see module docstring.
    """
    # Detect "a drop happened on this step" by comparing against the
    # previous snapshot. New drops are the strongest pressure signal —
    # they indicate the consumer is already shedding work.
    new_log_drops = event_log_drops - _state.last_log_drops
    new_edge_drops = edges_dropped - _state.last_edges_dropped

    _state.event_log_drops = event_log_drops
    _state.edges_dropped = edges_dropped
    _state.pending_edges = pending_edges
    _state.pending_symbols_total = pending_symbols_total
    _state.last_log_drops = event_log_drops
    _state.last_edges_dropped = edges_dropped

    if _overloaded.is_set():
        # In overload — apply CLEAR thresholds (must be below ALL
        # clear lines AND no drops on this step).
        if (
            pending_edges < _CLEAR_PENDING_EDGES
            and pending_symbols_total < _CLEAR_PENDING_SYMBOLS
            and new_log_drops == 0
            and new_edge_drops == 0
        ):
            _overloaded.clear()
    else:
        # Not in overload — apply TRIP thresholds (any one is enough).
        if (
            pending_edges >= _TRIP_PENDING_EDGES
            or pending_symbols_total >= _TRIP_PENDING_SYMBOLS
            or new_log_drops > 0
            or new_edge_drops > 0
        ):
            _overloaded.set()
    return _overloaded.is_set()


def is_overloaded() -> bool:
    """Lock-free flag check. Safe from any thread."""
    return _overloaded.is_set()


def wait_for_clear(timeout: float) -> bool:
    """Block up to ``timeout`` seconds for the overload flag to clear.

    Returns True iff the flag is clear on return (either it was clear
    on entry, or it cleared within ``timeout``). Returns False if the
    timeout elapsed while still overloaded.

    Bounded by design: the producer must not stall forever on a stuck
    consumer. Build progress is preferable to perfect smoothness.
    """
    if not _overloaded.is_set():
        return True
    # threading.Event.wait returns True when SET; we want the opposite.
    # Poll in small slices so a clear() is detected within ~10 ms.
    import time

    deadline = time.monotonic() + timeout
    while _overloaded.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        # Sleep slice — short enough that a clear is noticed promptly,
        # long enough that the polling cost is negligible.
        time.sleep(min(remaining, 0.01))
    return True


def snapshot() -> dict:
    """Diagnostic readout — safe from any thread.

    Used by /healthz-style endpoints to expose the counters Cochrane
    Finding 1c asks for (every emitted counter must be readable by at
    least one caller).
    """
    return {
        "overloaded": _overloaded.is_set(),
        "event_log_drops": _state.event_log_drops,
        "edges_dropped": _state.edges_dropped,
        "pending_edges": _state.pending_edges,
        "pending_symbols_total": _state.pending_symbols_total,
        "thresholds": {
            "pending_edges_trip": _TRIP_PENDING_EDGES,
            "pending_edges_clear": _CLEAR_PENDING_EDGES,
            "pending_symbols_trip": _TRIP_PENDING_SYMBOLS,
            "pending_symbols_clear": _CLEAR_PENDING_SYMBOLS,
        },
    }


def reset() -> None:
    """Clear all state. Called when the authority is rebuilt so a
    stale overload flag from the previous run cannot block the new
    producer."""
    _state.event_log_drops = 0
    _state.edges_dropped = 0
    _state.pending_edges = 0
    _state.pending_symbols_total = 0
    _state.last_log_drops = 0
    _state.last_edges_dropped = 0
    _overloaded.clear()
