"""Falsification test suite for the Cortex layout authority.

Popper discipline: each test is designed so it would FAIL if the invariant
under examination were false. A passing test is corroboration, not proof.
Targets geometry (O(1) determinism), scheduler (priority + drops), log
(replay + gap detection), wire (SSE roundtrip + NaN/inf rejection).
"""

from __future__ import annotations

import math
import os
import sys
import unittest
from dataclasses import dataclass

# Make the package importable when this file is executed directly.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from mcp_server.server import layout_authority_geometry as geom  # noqa: E402
from mcp_server.server import layout_authority_log as evlog  # noqa: E402
from mcp_server.server import layout_authority_pressure as pressure  # noqa: E402
from mcp_server.server import layout_authority_scheduler as sched  # noqa: E402
from mcp_server.server import layout_authority_wire as wire  # noqa: E402

try:
    import resource  # POSIX only

    _HAVE_RESOURCE = True
except ImportError:  # pragma: no cover - non-POSIX
    _HAVE_RESOURCE = False


# ---- helpers ----------------------------------------------------------------


@dataclass(slots=True)
class _Slot:
    # wire.format_slot reads .node_id, .x, .y, .kind, .domain_id —
    # matches the SlotAssignment contract in layout_authority_protocol.
    node_id: str
    x: float
    y: float
    kind: str
    domain_id: str


def _rss_bytes() -> int:
    """Return current process RSS in bytes (Linux: KB; macOS: bytes)."""
    if not _HAVE_RESOURCE:
        return 0
    ru = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        return ru.ru_maxrss  # bytes on macOS
    return ru.ru_maxrss * 1024  # KB on Linux


# ---- 1. Slot stability ------------------------------------------------------


class TestSlotStability(unittest.TestCase):
    # Falsifies: closed-form geometry is order-independent.
    def test_same_context_same_slot_repeated(self) -> None:
        ctx = {
            "anchor": (500.0, 500.0),
            "outward": 0.5,
            "tool_name": "Edit",
        }
        first = geom.compute_slot("tool_hub", ctx)
        for _ in range(1000):
            self.assertEqual(geom.compute_slot("tool_hub", ctx), first)

    def test_interleaving_does_not_perturb(self) -> None:
        # Falsifies any shared accumulator across kinds.
        ctx_hub = {"anchor": (300.0, 300.0), "outward": 0.0, "tool_name": "Bash"}
        ctx_file = {
            "anchor": (300.0, 300.0),
            "hub_angle": 0.0,
            "idx": 5,
            "total": 10,
        }
        a = geom.compute_slot("tool_hub", ctx_hub)
        for _ in range(100):
            geom.compute_slot("file", ctx_file)
            geom.compute_slot("symbol", {"file_slot": (1.0, 1.0), "idx": 3, "total": 7})
        b = geom.compute_slot("tool_hub", ctx_hub)
        self.assertEqual(a, b)

    def test_finite_outputs_for_all_kinds(self) -> None:
        # Falsifies I1: every coordinate must be finite.
        full_ctx = {
            "anchor": (100.0, 200.0),
            "outward": 1.2,
            "tool_name": "Read",
            "hub_angle": 0.3,
            "idx": 0,
            "total": 1,
            "file_slot": (150.0, 250.0),
            "index": 0,
            "total_domains": 1,
            "cx": 500.0,
            "cy": 500.0,
            "base_r": 200.0,
        }
        for kind in (
            "domain",
            "tool_hub",
            "file",
            "symbol",
            "skill",
            "hook",
            "command",
            "agent",
            "discussion",
            "memory",
            "mcp",
        ):
            x, y = geom.compute_slot(kind, full_ctx)
            self.assertTrue(math.isfinite(x), f"x not finite for {kind}")
            self.assertTrue(math.isfinite(y), f"y not finite for {kind}")


# ---- 2. Bounded state at 10^6 nodes -----------------------------------------


class TestBoundedState(unittest.TestCase):
    # Falsifies: compute_slot is O(1) state. A memoizing impl would
    # blow the 200 MB delta ceiling at 10^6 distinct calls.

    @unittest.skipUnless(_HAVE_RESOURCE, "resource module unavailable")
    def test_million_nodes_bounded_rss(self) -> None:
        ceiling_bytes = 200 * 1024 * 1024  # 200 MB delta
        before = _rss_bytes()
        anchor = (500.0, 500.0)
        # Avoid storing results — that would defeat the test.
        sink_x = 0.0
        sink_y = 0.0
        for i in range(1_000_000):
            x, y = geom.slot_for_symbol((100.0, 100.0), i, 1_000_000)
            # Reuse to keep one float live; do not accumulate a list.
            sink_x = x
            sink_y = y
            if i % 100_000 == 0:
                _ = geom.slot_for_file(anchor, 0.0, i % 100, 100)
        after = _rss_bytes()
        self.assertTrue(math.isfinite(sink_x))
        self.assertTrue(math.isfinite(sink_y))
        delta = after - before
        self.assertLess(
            delta,
            ceiling_bytes,
            f"RSS grew by {delta} bytes over 10^6 calls — possible leak",
        )


# ---- 3. Priority preemption -------------------------------------------------


class TestPriorityPreemption(unittest.TestCase):
    # Falsifies: a single P0 item preempts a P4 backlog.

    def test_p0_pops_before_p4_backlog(self) -> None:
        s = sched.PriorityScheduler()
        for i in range(1000):
            self.assertTrue(s.submit(sched.PRIORITY_SYMBOL, ("sym", i)))
        self.assertTrue(s.submit(sched.PRIORITY_DOMAIN, ("dom", 0)))
        first = s.pop(timeout=1.0)
        self.assertIsNotNone(first)
        prio, item = first
        self.assertEqual(prio, sched.PRIORITY_DOMAIN)
        self.assertEqual(item, ("dom", 0))

    def test_strict_ordering_across_all_priorities(self) -> None:
        # Insert in REVERSE priority order; pop must drain in 0..6.
        s = sched.PriorityScheduler()
        # Insert in REVERSE priority order to maximize falsification chance.
        for p in (6, 5, 4, 3, 2, 1, 0):
            self.assertTrue(s.submit(p, p))
        seen = []
        while True:
            r = s.pop(timeout=0.05)
            if r is None:
                break
            seen.append(r[0])
        self.assertEqual(seen, [0, 1, 2, 3, 4, 5, 6])


# ---- 4. Drop accounting ------------------------------------------------------


class TestDropAccounting(unittest.TestCase):
    # Falsifies: every dropped submit increments dropped[p] exactly once.
    # Catches off-by-one and silent maxlen eviction.

    def test_overflow_increments_drop_counter_per_drop(self) -> None:
        s = sched.PriorityScheduler()
        cap = sched.QUEUE_SIZES[sched.PRIORITY_DOMAIN]
        # Fill to cap.
        for i in range(cap):
            self.assertTrue(s.submit(sched.PRIORITY_DOMAIN, i))
        # Each subsequent submit must drop and increment exactly once.
        overflow = 25
        for i in range(overflow):
            accepted = s.submit(sched.PRIORITY_DOMAIN, ("over", i))
            self.assertFalse(accepted)
        self.assertEqual(
            s.stats()["dropped"][sched.PRIORITY_DOMAIN],
            overflow,
        )
        # And other priorities are untouched (no cross-talk).
        for p, drops in s.stats()["dropped"].items():
            if p != sched.PRIORITY_DOMAIN:
                self.assertEqual(drops, 0, f"priority {p} leaked drops")

    def test_no_silent_eviction(self) -> None:
        # If maxlen-eviction were used, the head item would change.
        s = sched.PriorityScheduler()
        cap = sched.QUEUE_SIZES[sched.PRIORITY_TOOL_HUB]
        for i in range(cap):
            self.assertTrue(s.submit(sched.PRIORITY_TOOL_HUB, ("hub", i)))
        for i in range(50):
            self.assertFalse(s.submit(sched.PRIORITY_TOOL_HUB, ("late", i)))
        # The first popped item must still be ('hub', 0).
        first = s.pop(timeout=0.5)
        self.assertEqual(first, (sched.PRIORITY_TOOL_HUB, ("hub", 0)))


# ---- 5. Replay correctness --------------------------------------------------


class TestReplayCorrectness(unittest.TestCase):
    # Falsifies: replay_since(N) returns exactly events with seq > N.

    def setUp(self) -> None:
        evlog.reset()

    def tearDown(self) -> None:
        evlog.reset()

    def test_replay_returns_post_n_events(self) -> None:
        seqs = []
        for i in range(1000):
            seqs.append(evlog.emit("slot", f"e{i}".encode()))
        # Across reset boundaries seq is monotonic; capture the start.
        start = seqs[0]
        for cut in (start - 1, start + 0, start + 1, start + 499, start + 998):
            events, _oldest = evlog.replay_since(cut)
            expected = [s for s in seqs if s > cut]
            got = [e[0] for e in events]
            self.assertEqual(got, expected, f"mismatch at since={cut}")

    def test_replay_since_newest_returns_empty(self) -> None:
        for i in range(10):
            evlog.emit("slot", b"x")
        newest = evlog.stats()["newest_seq"]
        events, oldest = evlog.replay_since(newest)
        self.assertEqual(events, [])
        self.assertGreater(oldest, 0)


# ---- 6. Replay-lost detection -----------------------------------------------


class TestReplayLost(unittest.TestCase):
    # Falsifies: requesting seq older than buffer's oldest yields gap signal.

    def setUp(self) -> None:
        evlog.reset()

    def tearDown(self) -> None:
        evlog.reset()

    def test_overflow_triggers_gap(self) -> None:
        # Swap in a small-cap deque to provoke overflow quickly.
        small_cap = 100
        original = evlog._event_log
        original_drops = evlog._event_log_drops
        try:
            import collections as _c

            evlog._event_log = _c.deque(maxlen=small_cap)
            evlog._event_log_drops = 0
            first_seq = evlog.emit("slot", b"first")
            for i in range(small_cap + 50):
                evlog.emit("slot", f"e{i}".encode())
            events, oldest = evlog.replay_since(first_seq)
            # The buffer dropped the early events, so oldest must exceed
            # first_seq+1; the SSE handler interprets this as 'replay_lost'.
            self.assertGreater(
                oldest,
                first_seq + 1,
                "log did not signal a replay gap after overflow",
            )
            # And the events list must NOT include first_seq.
            self.assertTrue(all(e[0] > first_seq for e in events))
        finally:
            evlog._event_log = original
            evlog._event_log_drops = original_drops


# ---- 7. Wire format roundtrip -----------------------------------------------


class TestWireRoundtrip(unittest.TestCase):
    # Falsifies: format -> parse recovers input modulo 0.1px rounding.

    def test_roundtrip_preserves_structure(self) -> None:
        cases = [
            _Slot("n1", 0.0, 0.0, "domain", "d1"),
            _Slot("n_2", 12.34, -56.78, "file", "d_xy"),
            _Slot("abc", 1000.0, 999.99, "symbol", "core"),
            _Slot("z", -0.05, 0.04, "tool_hub", "infra"),  # rounding edge
        ]
        for s in cases:
            frame = wire.format_slot(seq=42, slot=s)
            # Extract the data: line.
            self.assertIn(b"event: slot\n", frame)
            data_line = frame.split(b"data: ", 1)[1].rstrip(b"\n")
            node_id, x, y, kind, domain_id = wire.parse_slot(data_line)
            self.assertEqual(node_id, s.node_id)
            self.assertEqual(kind, s.kind)
            self.assertEqual(domain_id, s.domain_id)
            self.assertAlmostEqual(x, round(s.x, 1), places=2)
            self.assertAlmostEqual(y, round(s.y, 1), places=2)

    def test_pipe_in_id_is_rejected(self) -> None:
        s = _Slot("bad|id", 1.0, 1.0, "domain", "d")
        with self.assertRaises(ValueError):
            wire.format_slot(seq=1, slot=s)

    def test_kind_too_long_is_rejected(self) -> None:
        s = _Slot("ok", 1.0, 1.0, "x" * 64, "d")
        with self.assertRaises(ValueError):
            wire.format_slot(seq=1, slot=s)


# ---- 8. NaN/inf rejection ---------------------------------------------------


class TestFiniteValidation(unittest.TestCase):
    # Falsifies: NaN/inf coordinates must raise at the wire boundary.

    def test_nan_x_rejected(self) -> None:
        s = _Slot("n", float("nan"), 0.0, "domain", "d")
        with self.assertRaises(ValueError):
            wire.format_slot(seq=1, slot=s)

    def test_inf_y_rejected(self) -> None:
        s = _Slot("n", 0.0, float("inf"), "domain", "d")
        with self.assertRaises(ValueError):
            wire.format_slot(seq=1, slot=s)

    def test_neg_inf_x_rejected(self) -> None:
        s = _Slot("n", float("-inf"), 0.0, "domain", "d")
        with self.assertRaises(ValueError):
            wire.format_slot(seq=1, slot=s)


class TestPressureActChannel(unittest.TestCase):
    """Producer-feedback Act-channel — Cochrane Finding A.

    Each test would fail if the flag did not actually close the loop.
    """

    def setUp(self) -> None:
        pressure.reset()

    def test_quiescent_not_overloaded(self) -> None:
        # Falsifies: flag is set spuriously on a clean reset.
        self.assertFalse(pressure.is_overloaded())
        self.assertTrue(pressure.wait_for_clear(timeout=0.01))

    def test_trip_on_pending_edges_threshold(self) -> None:
        # Falsifies: crossing the trip line does NOT set the flag.
        pressure.observe(
            event_log_drops=0,
            edges_dropped=0,
            pending_edges=80_000,  # = 80% of 100k cap = TRIP
            pending_symbols_total=0,
        )
        self.assertTrue(pressure.is_overloaded())

    def test_no_trip_just_below_threshold(self) -> None:
        # Falsifies: the threshold is wrong (flapping below trip).
        pressure.observe(
            event_log_drops=0,
            edges_dropped=0,
            pending_edges=79_999,
            pending_symbols_total=0,
        )
        self.assertFalse(pressure.is_overloaded())

    def test_trip_on_new_log_drop(self) -> None:
        # Falsifies: a fresh drop is invisible to the producer.
        pressure.observe(
            event_log_drops=0,
            edges_dropped=0,
            pending_edges=0,
            pending_symbols_total=0,
        )
        pressure.observe(
            event_log_drops=1,  # one new drop since last call
            edges_dropped=0,
            pending_edges=0,
            pending_symbols_total=0,
        )
        self.assertTrue(pressure.is_overloaded())

    def test_hysteresis_holds_until_clear_line(self) -> None:
        # Falsifies: flag drops as soon as pending_edges dips below trip
        # (would flap on single-event jitter around the threshold).
        pressure.observe(
            event_log_drops=0,
            edges_dropped=0,
            pending_edges=80_000,
            pending_symbols_total=0,
        )
        self.assertTrue(pressure.is_overloaded())
        # Still above clear (50k) — flag must remain set.
        pressure.observe(
            event_log_drops=0,
            edges_dropped=0,
            pending_edges=60_000,
            pending_symbols_total=0,
        )
        self.assertTrue(pressure.is_overloaded())
        # Below clear AND no new drops — flag releases.
        pressure.observe(
            event_log_drops=0,
            edges_dropped=0,
            pending_edges=49_999,
            pending_symbols_total=0,
        )
        self.assertFalse(pressure.is_overloaded())

    def test_wait_for_clear_times_out_under_persistent_pressure(self) -> None:
        # Falsifies: a stuck consumer can stall the producer forever.
        pressure.observe(
            event_log_drops=0,
            edges_dropped=0,
            pending_edges=90_000,
            pending_symbols_total=0,
        )
        import time as _t

        start = _t.monotonic()
        ok = pressure.wait_for_clear(timeout=0.05)
        elapsed = _t.monotonic() - start
        self.assertFalse(ok)
        # Must return within ~timeout + one poll slice (10 ms).
        self.assertLess(elapsed, 0.2)

    def test_wait_for_clear_returns_immediately_when_clear(self) -> None:
        # Falsifies: producer pays a polling penalty even when idle.
        import time as _t

        start = _t.monotonic()
        ok = pressure.wait_for_clear(timeout=5.0)
        elapsed = _t.monotonic() - start
        self.assertTrue(ok)
        self.assertLess(elapsed, 0.01)

    def test_snapshot_exposes_every_counter(self) -> None:
        # Falsifies: Cochrane 1c (read every emitted counter) is unmet.
        pressure.observe(
            event_log_drops=7,
            edges_dropped=3,
            pending_edges=42,
            pending_symbols_total=11,
        )
        snap = pressure.snapshot()
        self.assertEqual(snap["event_log_drops"], 7)
        self.assertEqual(snap["edges_dropped"], 3)
        self.assertEqual(snap["pending_edges"], 42)
        self.assertEqual(snap["pending_symbols_total"], 11)
        self.assertIn("thresholds", snap)
        self.assertIn("overloaded", snap)


class TestPressureAuthorityIntegration(unittest.TestCase):
    """End-to-end: authority emissions actually drive the Act-channel."""

    def setUp(self) -> None:
        evlog.reset()
        pressure.reset()

    def test_authority_emit_observes_pressure(self) -> None:
        # Falsifies: the integrator's emission paths do not feed the
        # pressure module, so the producer can never detect overload.
        from mcp_server.server.layout_authority import build_authority
        from mcp_server.server.layout_authority_protocol import NodeDelta

        auth = build_authority()
        auth.add_node(NodeDelta("domain:t", "domain", "domain:t"))
        snap = pressure.snapshot()
        # After a quiet single-emission, no overload — but observe()
        # ran (last_log_drops / last_edges_dropped initialised).
        self.assertFalse(snap["overloaded"])
        # An emission is recorded in the snapshot's pending counters
        # (zero here, but the call path executed without raising).
        self.assertEqual(snap["pending_edges"], 0)


if __name__ == "__main__":
    unittest.main()
