"""Cortex layout-authority integrator.

Consolidates geometry + protocol + scheduler + log + wire into a single
``LayoutAuthority`` reference. Build worker calls add_node / add_edge /
request_subtree; SSE handler subscribes via subscribe() and drains
(seq, kind, payload_bytes) events ready for the wire.

Memory: O(domains x kinds) counters + bounded buffers (~256 KB worst).
Per-event: O(1) amortized.

Threading: single producer for emit(). Subscribers drain independently.

Invariants (see protocol module INVARIANTS):
    I1 finite (x,y) - wire layer verifies.
    I2 monotonic seq - log module assigns.
    I3 symbol-after-file - pending-symbols buffer flushes on file arrival.
    I4 file-before-tool_hub - falls back to domain anchor; final.
    I5 pending-edges - capped at 100k; oldest dropped.
    I7 domain-late - anchor deterministic from index alone.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Optional

from mcp_server.server import layout_authority_log as _log
from mcp_server.server import layout_authority_pressure as _pressure
from mcp_server.server import layout_authority_wire as _wire
from mcp_server.server.layout_authority_geometry import (
    base_radius,
    compute_slot,
    domain_anchor,
    outward_angle,
    tool_hub_angle,
)
from mcp_server.server.layout_authority_protocol import (
    EDGE_KINDS,
    NODE_KINDS,
    EdgeDelta,
    NodeDelta,
    SlotAssignment,
)


# ── Tunables ─────────────────────────────────────────────────────────────

_PENDING_EDGES_CAP = 100_000
_PENDING_SYMBOLS_CAP_PER_FILE = 4_096
_DEFAULT_DOMAIN_RESERVATION = 16  # initial Fibonacci slots reserved


# ── Internal helper structures ───────────────────────────────────────────


class _DomainRegistry:
    """Domain index + lazy Fibonacci anchor materialization (I7).

    Anchor = f(index, reserved_total, cx, cy, base_r). Indices are
    assigned on first sighting; reservation grows by chunks so anchors
    stay stable for already-placed domains (final per I4/I7).
    """

    def __init__(self, width: float, height: float) -> None:
        self._width = width
        self._height = height
        self._cx = width / 2.0
        self._cy = height / 2.0
        # domain_id -> (index, anchor (frozen), outward, base_r at freeze)
        self._index_of: dict[str, int] = {}
        self._anchors: dict[str, tuple[float, float]] = {}
        self._outwards: dict[str, float] = {}
        # Reserved domain count used for anchor math. Bumped only when a
        # NEW domain arrives AFTER reservation is exhausted; existing
        # anchors are NOT recomputed (they were frozen at first sighting).
        self._reserved = _DEFAULT_DOMAIN_RESERVATION

    def index_for(self, domain_id: str) -> int:
        idx = self._index_of.get(domain_id)
        if idx is not None:
            return idx
        idx = len(self._index_of)
        if idx >= self._reserved:
            # Grow reservation but do not back-edit prior anchors. New
            # anchor uses the new reservation; prior anchors retain their
            # first-sighting placement (final per I4/I7).
            self._reserved = idx + _DEFAULT_DOMAIN_RESERVATION
        self._index_of[domain_id] = idx
        base_r = base_radius(self._width, self._height, self._reserved)
        anchor = domain_anchor(idx, self._reserved, self._cx, self._cy, base_r)
        self._anchors[domain_id] = anchor
        self._outwards[domain_id] = outward_angle(anchor, self._cx, self._cy)
        return idx

    def anchor(self, domain_id: str) -> tuple[float, float]:
        if domain_id not in self._anchors:
            self.index_for(domain_id)
        return self._anchors[domain_id]

    def outward(self, domain_id: str) -> float:
        if domain_id not in self._outwards:
            self.index_for(domain_id)
        return self._outwards[domain_id]

    def base_r(self) -> float:
        return base_radius(self._width, self._height, max(self._reserved, 1))

    def total(self) -> int:
        return self._reserved

    def cx(self) -> float:
        return self._cx

    def cy(self) -> float:
        return self._cy


# ── Validation helpers ───────────────────────────────────────────────────


def _validate_node(delta: NodeDelta) -> None:
    if delta.kind not in NODE_KINDS:
        raise ValueError(f"unknown node kind: {delta.kind!r}")
    if not delta.node_id:
        raise ValueError("node_id must be non-empty")
    if not delta.domain_id:
        raise ValueError("domain_id must be non-empty")
    if delta.kind == "domain" and delta.domain_id != delta.node_id:
        raise ValueError("domain node requires domain_id == node_id")
    if delta.kind == "tool_hub" and not delta.tool_name:
        raise ValueError("tool_hub node requires non-empty tool_name")
    if delta.kind == "symbol" and not delta.parent_id:
        raise ValueError("symbol node requires parent_id")


def _validate_edge(delta: EdgeDelta) -> None:
    if delta.kind not in EDGE_KINDS:
        raise ValueError(f"unknown edge kind: {delta.kind!r}")
    if not delta.source_id or not delta.target_id:
        raise ValueError("edge endpoints must be non-empty")


# ── Core integrator ──────────────────────────────────────────────────────


class LayoutAuthority:
    """Reference layout authority: counters + slot emission + buffers.

    Per-method preconditions/postconditions follow the protocol module
    contracts (NodeDelta / EdgeDelta docstrings). All methods are
    O(1) amortized; no method blocks.
    """

    def __init__(self, width: float = 1000.0, height: float = 1000.0) -> None:
        self._registry = _DomainRegistry(width, height)
        # (domain_id, kind) -> running count (also = next idx for that bucket).
        self._counts: dict[tuple[str, str], int] = {}
        # node_id -> SlotAssignment (final once placed; I4/I7).
        self._slots: dict[str, SlotAssignment] = {}
        # tool_hub node_id -> hub_angle (cached for files orbiting it).
        self._hub_angles: dict[str, float] = {}
        # I3 buffer: file_id -> [NodeDelta, ...] of symbols awaiting file slot.
        self._pending_symbols: dict[str, list[NodeDelta]] = {}
        # Running total of buffered symbols across all files. Maintained
        # incrementally so _observe_pressure is O(1) per emit instead of
        # O(files) — summing the dict on every add_node/add_edge made the
        # producer O(N×files) and stalled large builds (86k-edge memories
        # batch grinding at 98% CPU for minutes). source: measured
        # 2026-05-27 on the rebased streaming branch.
        self._pending_symbols_count = 0
        # I5 buffer: ordered (src,tgt) -> EdgeDelta; oldest dropped on cap.
        self._pending_edges: "OrderedDict[tuple[str, str], EdgeDelta]" = OrderedDict()
        # Counters surfaced via stats(); not load-bearing for correctness.
        self._slots_emitted = 0
        self._edges_emitted = 0
        self._edges_dropped = 0
        # Producer-side mutex (single producer expected; defensive only).
        self._lock = threading.Lock()
        self._closed = False

    # ── Public API (LayoutAuthority protocol) ──────────────────────────

    def add_node(self, delta: NodeDelta) -> None:
        _validate_node(delta)
        with self._lock:
            if self._closed:
                return
            slot = self._place_node(delta)
            if slot is None:
                return  # buffered (I3 symbol awaiting file)
            self._emit_slot(slot)
            # Symbol arrival via flush is handled inside _place_node->flush.
            self._try_flush_pending_edges_for(delta.node_id)

    def add_edge(self, delta: EdgeDelta) -> None:
        _validate_edge(delta)
        with self._lock:
            if self._closed:
                return
            if delta.source_id in self._slots and delta.target_id in self._slots:
                self._emit_edge(delta)
                return
            self._buffer_edge(delta)

    def request_subtree(self, domain_id: str) -> None:
        # Re-emit known slots for this domain. No reseat (slots final).
        # No-op if domain unknown (idempotent on a still-building graph).
        with self._lock:
            if self._closed:
                return
            if domain_id not in self._registry._index_of:  # noqa: SLF001
                return
            for slot in list(self._slots.values()):
                if slot.domain_id == domain_id:
                    self._emit_slot(slot)

    def subscribe(self):
        return _log.subscribe()

    def unsubscribe(self, q) -> None:
        _log.unsubscribe(q)

    def done(self) -> None:
        with self._lock:
            if self._closed:
                return
            seq = _log._event_seq + 1  # noqa: SLF001
            payload = _wire.format_done(
                seq=seq,
                total_slots=self._slots_emitted,
                total_edges=self._edges_emitted,
            )
            _log.emit("done", payload)
            self._closed = True

    def stats(self) -> dict:
        with self._lock:
            return {
                "slots_emitted": self._slots_emitted,
                "edges_emitted": self._edges_emitted,
                "edges_dropped": self._edges_dropped,
                "pending_symbols": self._pending_symbols_count,
                "pending_edges": len(self._pending_edges),
                "domains": len(self._registry._index_of),  # noqa: SLF001
            }

    def _observe_pressure(self) -> None:
        """Update the producer-feedback Act-channel.

        Called from the hotspots where the producer just observed (or
        could have observed) a pressure event: edge buffered, symbol
        buffered, emission completed. Single-producer precondition is
        already in force (caller holds ``self._lock``).
        """
        # O(1): read the running counter instead of summing the dict.
        # _event_log_drops is single-producer-written by _log.emit; we
        # read it without the log lock because we are the single
        # producer (Cochrane: no cross-producer race possible here).
        _pressure.observe(
            event_log_drops=_log._event_log_drops,  # noqa: SLF001
            edges_dropped=self._edges_dropped,
            pending_edges=len(self._pending_edges),
            pending_symbols_total=self._pending_symbols_count,
        )

    # ── Internal placement ─────────────────────────────────────────────

    def _place_node(self, delta: NodeDelta) -> Optional[SlotAssignment]:
        """Compute and register a slot. Returns None if buffered (I3)."""
        # Symbol awaiting file: buffer + return None.
        if delta.kind == "symbol":
            file_id = delta.parent_id
            if file_id not in self._slots:
                buf = self._pending_symbols.setdefault(file_id, [])
                if len(buf) < _PENDING_SYMBOLS_CAP_PER_FILE:
                    buf.append(delta)
                    self._pending_symbols_count += 1
                self._observe_pressure()
                return None

        slot = self._compute_assignment(delta)
        self._slots[delta.node_id] = slot
        # Side-effects beyond slot registration:
        if delta.kind == "tool_hub":
            self._hub_angles[delta.node_id] = self._tool_hub_angle_for(delta)
        return slot

    def _compute_assignment(self, delta: NodeDelta) -> SlotAssignment:
        """Pure: turn a NodeDelta into a SlotAssignment via geometry."""
        domain_id = delta.domain_id
        kind = delta.kind
        # Increment bucket counter; idx is pre-increment count.
        idx = self._counts.get((domain_id, kind), 0)
        self._counts[(domain_id, kind)] = idx + 1

        ctx = self._geometry_ctx(delta, idx)
        x, y = compute_slot(kind, ctx)
        # seq is assigned at emit time by the log; we stash 0 here and
        # rebuild SlotAssignment at emit so the wire sees the real seq.
        return SlotAssignment(
            seq=0,
            node_id=delta.node_id,
            x=float(x),
            y=float(y),
            kind=kind,
            domain_id=domain_id,
        )

    def _geometry_ctx(self, delta: NodeDelta, idx: int) -> dict:
        """Build the kind-specific ctx dict for compute_slot."""
        kind = delta.kind
        domain_id = delta.domain_id
        reg = self._registry

        if kind == "domain":
            return {
                "index": reg.index_for(domain_id),
                "total_domains": reg.total(),
                "cx": reg.cx(),
                "cy": reg.cy(),
                "base_r": reg.base_r(),
            }

        anchor = reg.anchor(domain_id)
        outward = reg.outward(domain_id)

        if kind == "tool_hub":
            return {
                "anchor": anchor,
                "outward": outward,
                "tool_name": delta.tool_name or "",
            }
        if kind == "file":
            hub_angle = outward
            if delta.parent_id and delta.parent_id in self._hub_angles:
                hub_angle = self._hub_angles[delta.parent_id]
            # Bucket idx is per (domain, kind) — approximates "files in
            # primary hub" since the build worker bins them per-hub.
            total = max(idx + 1, 1)
            return {
                "anchor": anchor,
                "hub_angle": hub_angle,
                "idx": idx,
                "total": total,
            }
        if kind == "symbol":
            file_slot = self._slots[delta.parent_id]  # type: ignore[index]
            file_xy = (file_slot.x, file_slot.y)
            # Per-file symbol idx (separate from domain bucket):
            sym_key = ("__sym__", delta.parent_id or "")
            sym_idx = self._counts.get(sym_key, 0)
            self._counts[sym_key] = sym_idx + 1
            total = max(sym_idx + 1, 1)
            return {"file_slot": file_xy, "idx": sym_idx, "total": total}

        # skill/hook/command/agent/discussion/memory/mcp/entity
        total = max(idx + 1, 1)
        return {
            "anchor": anchor,
            "outward": outward,
            "idx": idx,
            "total": total,
        }

    def _tool_hub_angle_for(self, delta: NodeDelta) -> float:
        outward = self._registry.outward(delta.domain_id)
        return tool_hub_angle(outward, delta.tool_name or "")

    # ── Emission ───────────────────────────────────────────────────────

    def _emit_slot(self, slot: SlotAssignment) -> None:
        # Peek next seq so the SSE 'id:' header matches the log's
        # assignment. Single-producer invariant on emit() makes this
        # safe (see layout_authority_log module docstring).
        seq = _log._event_seq + 1  # noqa: SLF001  peek-before-emit
        sealed = SlotAssignment(
            seq=seq,
            node_id=slot.node_id,
            x=slot.x,
            y=slot.y,
            kind=slot.kind,
            domain_id=slot.domain_id,
        )
        payload = _wire.format_slot(seq, sealed)
        actual_seq = _log.emit("slot", payload)
        assert actual_seq == seq, "log seq diverged from peek (multi-producer?)"
        self._slots[sealed.node_id] = sealed
        self._slots_emitted += 1
        if sealed.kind == "file":
            self._flush_pending_symbols(sealed.node_id)
        # After emission the log's drop counter and the local
        # pending-* sizes may have shifted (the log can have evicted
        # an old event under the ring cap, the symbol flush above may
        # have shrunk pending_symbols). Update the Act-channel so the
        # producer's next between-batches check is accurate.
        self._observe_pressure()

    def _emit_edge(self, edge: EdgeDelta) -> None:
        seq = _log._event_seq + 1  # noqa: SLF001
        payload = _wire.format_edge(seq, edge)
        _log.emit("edge", payload)
        self._edges_emitted += 1

    # ── Buffer flush helpers ───────────────────────────────────────────

    def _flush_pending_symbols(self, file_id: str) -> None:
        pending = self._pending_symbols.pop(file_id, None)
        if not pending:
            return
        self._pending_symbols_count -= len(pending)
        for sym in pending:
            slot = self._compute_assignment(sym)
            self._slots[sym.node_id] = slot
            self._emit_slot(slot)
            self._try_flush_pending_edges_for(sym.node_id)

    def _buffer_edge(self, delta: EdgeDelta) -> None:
        key = (delta.source_id, delta.target_id)
        if key in self._pending_edges:
            self._pending_edges.move_to_end(key)
            self._pending_edges[key] = delta
            return
        if len(self._pending_edges) >= _PENDING_EDGES_CAP:
            # Drop oldest (FIFO eviction per I5).
            self._pending_edges.popitem(last=False)
            self._edges_dropped += 1
        self._pending_edges[key] = delta
        self._observe_pressure()

    def _try_flush_pending_edges_for(self, node_id: str) -> None:
        if not self._pending_edges:
            return
        ready: list[tuple[str, str]] = []
        for key, edge in self._pending_edges.items():
            if key[0] != node_id and key[1] != node_id:
                continue
            if edge.source_id in self._slots and edge.target_id in self._slots:
                ready.append(key)
        for key in ready:
            edge = self._pending_edges.pop(key)
            self._emit_edge(edge)


# ── Factory ──────────────────────────────────────────────────────────────


def build_authority(width: float = 1000.0, height: float = 1000.0) -> LayoutAuthority:
    """Construct a fresh LayoutAuthority. Resets the global event log
    so the new build starts from a clean replay window. The seq counter
    persists across resets (see layout_authority_log.reset docstring).

    Also resets the producer-feedback Act-channel — otherwise a stale
    overload flag from the previous run would block the new producer
    until the next observe() call corrected it.
    """
    _log.reset()
    _pressure.reset()
    return LayoutAuthority(width=width, height=height)


# ── Smoke test ───────────────────────────────────────────────────────────


if __name__ == "__main__":
    auth = build_authority()
    auth.add_node(NodeDelta("domain:cortex", "domain", "domain:cortex"))
    auth.add_node(NodeDelta("file:abc", "file", "domain:cortex"))
    auth.add_node(
        NodeDelta("symbol:foo", "symbol", "domain:cortex", parent_id="file:abc")
    )
    auth.add_edge(EdgeDelta("symbol:foo", "file:abc", "defined_in"))

    # Subscribe AFTER emission to demonstrate the live-stream path; for
    # smoke purposes drain via replay since 0 to capture the full set.
    events, _oldest = _log.replay_since(0)
    print(f"Emitted {len(events)} events:")
    for seq, kind, payload in events:
        print(f"  seq={seq} kind={kind} bytes={len(payload)}")
