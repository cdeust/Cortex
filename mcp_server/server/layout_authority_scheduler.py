"""Priority-displaced scheduler for the Cortex layout authority.

Pattern (Hamilton 1969, Apollo 11 1202/1201 alarm response):
    Higher-priority work always preempts lower-priority. When the work
    queue saturates, low-priority items are dropped FIRST. The
    high-priority path NEVER starves and the producer NEVER blocks.

Priority levels (highest = most critical for visualization correctness):

    P0 — domain hubs (kind == 'domain')
        Without these, nothing else can be placed. NEVER dropped in
        practice (cap is generously above population).

    P1 — tool_hubs (kind == 'tool_hub')
        L3 files attach to these. Dropping a tool_hub orphans its
        files. Cap generously above population.

    P2 — files (kind == 'file')
        Symbols attach to these. Dropping a file orphans its symbols.
        Dropped only under catastrophic burst.

    P3 — L1 setup (skill/hook/command/agent/mcp), L4 discussions,
         L5 memories, L5+E entities
        Dropping these loses individual nodes but the topology stays
        coherent.

    P4 — symbols (kind == 'symbol')
        Highest volume, lowest individual importance. Dropped first
        among nodes — ~90% of symbols visible is fine.

    P5 — edges (any add_edge call)
        Lines on a canvas. Pretty but not topologically critical.
        Dropped before any node-level work is dropped.

    P6 — request_subtree
        Whole-subtree recompute. Always deferred until P0-P5 are
        empty. Coalesced (multiple requests for the same subtree
        collapse to one).

Source: Hamilton, M. H. & Hackler, W. R. (2008). "Universal Systems
Language: Lessons Learned from Apollo." IEEE Computer 41(12), 34–43,
section II ("Asynchronous, distributed, real-time"). The AGC
EXECUTIVE / BAILOUT / RESTART routines (LUMINARY 1A) shed
low-priority jobs by dropping their vac-area entries and continued
running with high-priority state intact.

Memory rationale (zetetic):
    Naive QUEUE_SIZES with P4=500k × ~80B NodeDelta = ~40 MB just for
    P4. That breaches the 8 MB working-set ceiling. We adopt option 1
    from the design brief: cap P4 at 64k. Sustained working set is
    much smaller because pop() drains continuously; the caps bound
    only burst absorption.

    Worst-case (all queues full, pointer + small-dataclass ~80B):
        P0:   1_000 *  80 =     80_000
        P1:   1_000 *  80 =     80_000
        P2:  16_000 *  80 =  1_280_000
        P3:  32_000 *  80 =  2_560_000
        P4:  64_000 *  80 =  5_120_000
        P5: 128_000 *  80 = 10_240_000
        P6:     100 *  80 =      8_000
        Total ≈ 19.4 MB worst-case (same order as 8 MB ceiling).
    Sustained drain keeps actual residency one to two orders below.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


# Per-priority bounded-deque sizes.
# source: design brief option 1 ("Cap P4 at 64k"); see module docstring
# for the worst-case memory derivation.
QUEUE_SIZES: dict[int, int] = {
    0: 1_000,  # P0 domains          — ~11 in practice
    1: 1_000,  # P1 tool hubs        — ~70 in practice
    2: 16_000,  # P2 files            — ~30k in practice (drops above)
    3: 32_000,  # P3 setup/discussion/memories/entities
    4: 64_000,  # P4 symbols          — high volume, drop first among nodes
    5: 128_000,  # P5 edges            — typically 4× nodes; drop before nodes
    6: 100,  # P6 subtree requests — coalesced
}

PRIORITY_DOMAIN = 0
PRIORITY_TOOL_HUB = 1
PRIORITY_FILE = 2
PRIORITY_OTHER_NODE = 3
PRIORITY_SYMBOL = 4
PRIORITY_EDGE = 5
PRIORITY_SUBTREE = 6


def priority_for_node(kind: str) -> int:
    """Map a node kind to its scheduling priority (lower = more critical)."""
    if kind == "domain":
        return PRIORITY_DOMAIN
    if kind == "tool_hub":
        return PRIORITY_TOOL_HUB
    if kind == "file":
        return PRIORITY_FILE
    if kind == "symbol":
        return PRIORITY_SYMBOL
    return PRIORITY_OTHER_NODE


def priority_for_edge() -> int:
    """All edges share a single priority — drop before any node."""
    return PRIORITY_EDGE


@dataclass
class Stats:
    """Per-priority counters for /api/layout/stats observability.

    queued  — cumulative successful submits (monotonic).
    dropped — cumulative drops due to a full queue (monotonic).
    """

    queued: dict[int, int] = field(default_factory=lambda: {p: 0 for p in QUEUE_SIZES})
    dropped: dict[int, int] = field(default_factory=lambda: {p: 0 for p in QUEUE_SIZES})


class PriorityScheduler:
    """Bounded multi-queue scheduler with priority-displaced shedding.

    submit(priority, item)
        Non-blocking. Returns True iff accepted; False if the priority's
        queue is at cap (item dropped, counter incremented). The
        producer never blocks — that is the Hamilton invariant.

    pop(timeout=None)
        Returns (priority, item) for the highest-priority non-empty
        queue. Blocks up to `timeout` seconds for new work. None on
        timeout.

    coalesce_subtree(domain_id)
        Idempotent insert into P6: duplicate requests collapse to a
        single pending entry. Without this, a viewport drag firing
        ~10 req/s grows the queue unbounded.

    stats()
        Snapshot of queued/dropped counters and current queue lengths.

    Memory: a deque per priority, each capped per QUEUE_SIZES. The
    caller MUST keep items small (NodeDelta/EdgeDelta or just a node
    id reference); the actual node payload is held by reference once
    in the authority's main store.
    """

    def __init__(self) -> None:
        self._queues: dict[int, deque] = {p: deque(maxlen=None) for p in QUEUE_SIZES}
        # maxlen=None because we want explicit drop accounting on submit
        # rather than silent left-pop eviction that maxlen would do.
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._stats = Stats()
        self._priorities_sorted = sorted(QUEUE_SIZES.keys())

    # ---- producer side --------------------------------------------------

    def submit(self, priority: int, item: object) -> bool:
        """Non-blocking enqueue. Returns False if dropped."""
        if priority not in QUEUE_SIZES:
            raise ValueError(f"unknown priority: {priority}")
        cap = QUEUE_SIZES[priority]
        with self._lock:
            q = self._queues[priority]
            if len(q) >= cap:
                self._stats.dropped[priority] += 1
                return False
            q.append(item)
            self._stats.queued[priority] += 1
            self._not_empty.notify()
            return True

    def coalesce_subtree(self, domain_id: str) -> bool:
        """Idempotent insert into P6. Returns True if newly enqueued."""
        with self._lock:
            q = self._queues[PRIORITY_SUBTREE]
            # Linear scan is fine: cap is 100, and P6 traffic is low.
            for existing in q:
                if existing == domain_id:
                    return False
            cap = QUEUE_SIZES[PRIORITY_SUBTREE]
            if len(q) >= cap:
                self._stats.dropped[PRIORITY_SUBTREE] += 1
                return False
            q.append(domain_id)
            self._stats.queued[PRIORITY_SUBTREE] += 1
            self._not_empty.notify()
            return True

    # ---- consumer side --------------------------------------------------

    def pop(self, timeout: Optional[float] = None) -> Optional[tuple[int, object]]:
        """Block until the next highest-priority item is ready.

        Returns (priority, item) or None on timeout. Strict priority:
        a single P0 item preempts an unbounded backlog at lower
        priorities — that is the displaced-scheduling guarantee.
        """
        with self._not_empty:
            deadline = None if timeout is None else time.monotonic() + timeout
            while True:
                picked = self._pop_highest_locked()
                if picked is not None:
                    return picked
                if timeout is None:
                    self._not_empty.wait()
                else:
                    remaining = deadline - time.monotonic()  # type: ignore[operator]
                    if remaining <= 0:
                        return None
                    self._not_empty.wait(timeout=remaining)

    def _pop_highest_locked(self) -> Optional[tuple[int, object]]:
        """Caller must hold self._lock."""
        for p in self._priorities_sorted:
            q = self._queues[p]
            if q:
                return (p, q.popleft())
        return None

    # ---- observability --------------------------------------------------

    def stats(self) -> dict:
        """Snapshot for /api/layout/stats — safe to call from any thread."""
        with self._lock:
            return {
                "queued": dict(self._stats.queued),
                "dropped": dict(self._stats.dropped),
                "lengths": {p: len(self._queues[p]) for p in QUEUE_SIZES},
                "caps": dict(QUEUE_SIZES),
            }

    def total_pending(self) -> int:
        """Sum of all queue lengths — useful for backpressure signals."""
        with self._lock:
            return sum(len(q) for q in self._queues.values())

    def is_overloaded(self, threshold: float = 0.8) -> bool:
        """True iff any queue is above `threshold` of its cap.

        Surfaces "1202-class" condition to the producer-facing
        endpoint so it can advertise degradation upstream rather
        than failing silently.
        """
        with self._lock:
            for p, q in self._queues.items():
                if len(q) >= QUEUE_SIZES[p] * threshold:
                    return True
            return False
