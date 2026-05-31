"""In-memory replayable event stream for the live-build SSE protocol.

The first visit to the graph viz on a cold cache (no precomputed binary
snapshot) used to block until the entire ingest finished — ~1–3 min on
a 100 k-memory dev DB. This module wires a live stream of per-source
batches so the browser receives node/edge deltas AS THE BUILDER
PRODUCES THEM, and the user watches the graph grow instead of waiting
for a final paint.

Why this exists vs the layout_authority SSE infrastructure on the same
branch: layout_authority emits closed-form slot assignments in a tight
binary wire format aimed at the streaming_canvas renderer. The
force-directed renderer used by the page today (workflow_graph.js)
consumes JSON node/edge dicts via JUG.appendGraphDelta, so we publish
the SAME dict shape /api/graph would have returned, just chunked into
many small events. No new client decoder needed.

Why the per-source on_batch wiring on this branch ground to a halt
earlier: it routed every node/edge through _merge + LayoutAuthority
synchronously in the build thread. _merge does an O(cache) kind_counts
recompute on every call, and the 107 k-memory batch made that a multi-
minute stall. This event stream is intentionally JUST a queue: emit
appends to a deque, returns immediately, no per-item bookkeeping. The
cumulative cache (_graph_cache) is still populated in ONE _merge at
the end of the build, where the O(cache) recompute is paid once on
the full graph, not per source.

Concurrency:
    emit() / close() / reset() — called from the build worker thread
        (single producer per build, multiple subscribers can be reading
        concurrently). Uses an internal condition variable to wake
        sleeping subscribers when events arrive.
    subscribe() — called from any SSE handler thread, yields events
        in insertion order starting at index ``since`` (Last-Event-ID
        resume semantics). Returns when close() fires + the subscriber
        has drained.

Memory: bounded by max_events (default 100 k). At ~2 KB per chunked
batch this caps the stream at ~200 MB worst case, but typical builds
emit O(100) events of O(1000) nodes/edges each = O(10 MB). The cap
exists so a runaway producer doesn't fill memory if every subscriber
disconnects mid-stream.
"""

from __future__ import annotations

import collections
import json
import threading
from typing import Any, Iterator


class GraphEventStream:
    """Append-only event log + condition-variable fan-out.

    Mirrors the layout_authority_log pattern (single-producer write,
    multi-subscriber read, replay-since-index) but stores dict-shaped
    JSON batches instead of binary slot frames.
    """

    __slots__ = ("_buf", "_lock", "_cond", "_closed", "_max")

    def __init__(self, max_events: int = 100_000) -> None:
        self._buf: collections.deque = collections.deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._closed = False
        self._max = max_events

    # ── Producer side ───────────────────────────────────────────────

    def emit(
        self,
        label: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        *,
        chunk: int = 1000,
    ) -> int:
        """Append a batch (chunked into sub-batches of ``chunk`` items).

        Returns the number of sub-events emitted. Empty inputs are a
        no-op (returns 0). Each emitted sub-event carries a synthetic
        sub-label so the client can log progression without inferring.
        """
        if not nodes and not edges:
            return 0
        emitted = 0
        n_total = len(nodes)
        e_total = len(edges)
        # Slice nodes and edges in parallel so a giant memories batch
        # (107 k nodes + 107 k edges) lands as ~107 chunks of ~1000 each.
        # Each sub-event JSON-serialises to roughly 100–300 KB —
        # browser-friendly, no SSE buffer pressure.
        total = max(n_total, e_total)
        step = max(1, chunk)
        with self._cond:
            for off in range(0, total, step):
                n_chunk = nodes[off : off + step]
                e_chunk = edges[off : off + step]
                if not n_chunk and not e_chunk:
                    continue
                self._buf.append(
                    {
                        "label": label,
                        "off": off,
                        "n_total": n_total,
                        "e_total": e_total,
                        "nodes": n_chunk,
                        "edges": e_chunk,
                    }
                )
                emitted += 1
            if emitted:
                self._cond.notify_all()
        return emitted

    def close(self) -> None:
        """Mark the stream complete. Subscribers drain remaining events
        then exit their subscribe() loop. Idempotent."""
        with self._cond:
            if self._closed:
                return
            self._closed = True
            self._cond.notify_all()

    def reset(self) -> None:
        """Start a fresh stream (called when a new build kicks). Wakes
        any current subscribers so they observe end-of-stream and the
        new build's stream replaces this one in the global slot."""
        with self._cond:
            self._buf.clear()
            self._closed = True
            self._cond.notify_all()
        # Recreate the underlying buffers so a subsequent emit appends
        # to a fresh queue. _closed is reset on the next emit-or-open.
        self._buf = collections.deque(maxlen=self._max)
        self._closed = False

    # ── Subscriber side ─────────────────────────────────────────────

    def stats(self) -> dict:
        with self._lock:
            return {"count": len(self._buf), "closed": self._closed}

    def subscribe(
        self, since: int = 0, *, timeout: float = 30.0
    ) -> Iterator[tuple[int, dict]]:
        """Generator yielding ``(index, event_dict)`` from ``since``.

        Returns when (a) the stream is closed AND the subscriber has
        drained all events, or (b) ``timeout`` seconds elapse with no
        new events and the stream is still open (the SSE handler can
        send a heartbeat and re-call subscribe with the next index).

        ``index`` is the position in the buffer; clients can use it as
        Last-Event-ID for resume after a reconnect.
        """
        i = since
        while True:
            with self._cond:
                if i >= len(self._buf) and not self._closed:
                    # Wait for new events OR close, up to ``timeout`` per
                    # call. Timeout is PER-WAIT (not cumulative across
                    # multiple events), so a long-running build with
                    # steady event flow never spuriously times out — it
                    # only returns when truly idle for ``timeout`` s.
                    self._cond.wait(timeout=timeout)
                if i < len(self._buf):
                    ev = self._buf[i]
                elif self._closed:
                    # Closed AND drained.
                    return
                else:
                    # Idle timeout without new events — return so the
                    # SSE handler can emit a heartbeat and re-subscribe.
                    return
            yield i, ev
            i += 1


# ── Process-wide singleton ──────────────────────────────────────────
# One stream per process. A new build resets it (see reset()); active
# subscribers observe close-of-stream and reconnect, which is exactly
# the behaviour SSE clients implement by default.

_stream = GraphEventStream()


def get_stream() -> GraphEventStream:
    return _stream


def emit(label: str, nodes: list, edges: list, *, chunk: int = 1000) -> int:
    return _stream.emit(label, nodes, edges, chunk=chunk)


def close() -> None:
    _stream.close()


def reset() -> None:
    global _stream
    _stream.reset()


# ── SSE wire helpers ────────────────────────────────────────────────


def _json_default(o):
    """Fallback for non-JSON-native types we still want to surface.

    Memory nodes carry datetime fields (last_accessed, stage_entered_at,
    …) — pydantic's ``model_dump`` keeps them as datetime objects rather
    than ISO strings, so a naïve ``json.dumps`` raises ``TypeError:
    Object of type datetime is not JSON serializable``. Stringify
    anything we don't natively serialise.
    """
    try:
        return o.isoformat()
    except AttributeError:
        return str(o)


def format_event(index: int, event: dict) -> bytes:
    """Format one event as an SSE frame.

    ``id:`` is the buffer index so the browser can resume via the
    standard ``Last-Event-ID`` header on reconnect.
    """
    payload = json.dumps(event, separators=(",", ":"), default=_json_default)
    return (f"id: {index}\nevent: batch\ndata: {payload}\n\n").encode("utf-8")


def format_done(total_nodes: int, total_edges: int) -> bytes:
    payload = json.dumps(
        {"total_nodes": total_nodes, "total_edges": total_edges},
        separators=(",", ":"),
    )
    return (f"event: done\ndata: {payload}\n\n").encode("utf-8")


def format_heartbeat() -> bytes:
    return b": heartbeat\n\n"
