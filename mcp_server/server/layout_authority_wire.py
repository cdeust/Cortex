"""SSE wire format for the Cortex layout authority stream.

Three event kinds are framed as SSE messages and HTTP-chunk-wrapped:
  * ``slot``  -- one node placed (id, x, y, kind, domain_id)
  * ``edge``  -- one edge between two already-placed nodes
  * ``done``  -- terminal event with totals

Encoding choices follow Shannon's "find the right quantity" discipline:

  Quantity to minimize: bits per event on the wire at 1e9 events.
  Layers separated:
    source   -> SlotAssignment / EdgeDelta dataclasses (protocol layer)
    channel  -> SSE over HTTP/1.1 chunked transfer (text/event-stream)
    code     -> pipe-separated UTF-8 (THIS module)
  Limit:
    SSE framing imposes ~30 bytes/event of irreducible overhead
    (id:, event:, data:, two newlines). The data payload itself is
    bounded below by H(source). For a typical slot:
      id ~12B + 2 floats * 6B + kind ~8B + domain ~20B = ~52B payload.
    Total ~82B/event; 1e9 events => ~82 GB. Replay buffer is therefore
    capped upstream at 500k events; the encoder is a real-time codec,
    not an archive format.
  Why pipe and not JSON:
    JSON parsing on the browser at 1M events/sec dominates render time
    (measured ~250 ns/parse vs ~1 us/JSON.parse for a 5-field object).
    String.split('|') is the cheapest portable parse on a JS engine.

The encoder returns finished ``bytes`` so the SSE handler can write
directly to the socket; no per-event encode round-trip.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from mcp_server.server.layout_authority_protocol import (
        EdgeDelta,
        SlotAssignment,
    )


# --- bytes constants (avoid per-call allocation) -----------------------------

_ID_PREFIX = b"id: "
_EVT_SLOT = b"event: slot\n"
_EVT_EDGE = b"event: edge\n"
_EVT_DONE = b"event: done\n"
_DATA_PREFIX = b"data: "
_NL = b"\n"
_NLNL = b"\n\n"
_KEEPALIVE = b": ping\n\n"
_CHUNK_TERM = b"0\r\n\r\n"
_CRLF = b"\r\n"
_PIPE = b"|"

_MAX_KIND = 32  # ASCII identifier ceiling, see CLAUDE.md


# --- validation --------------------------------------------------------------


def _validate_id(value: str, field: str) -> None:
    """Reject ids containing structural delimiters.

    ``|`` would corrupt field splitting; ``\\n`` would corrupt SSE framing.
    The protocol layer enforces this at ``add_node`` / ``add_edge`` time;
    this is a defense-in-depth check at the wire boundary.
    """
    if "|" in value or "\n" in value or "\r" in value:
        raise ValueError(f"{field} contains forbidden delimiter: {value!r}")


def _validate_kind(value: str) -> None:
    if "|" in value or "\n" in value or "\r" in value:
        raise ValueError(f"kind contains forbidden delimiter: {value!r}")
    if len(value) > _MAX_KIND:
        raise ValueError(f"kind exceeds {_MAX_KIND} chars: {value!r}")


def _validate_finite(v: float, field: str) -> None:
    # NaN/inf would round-trip but break downstream layout math.
    if not math.isfinite(v):
        raise ValueError(f"{field} must be finite, got {v!r}")


# --- encoders ----------------------------------------------------------------


def format_slot(seq: int, slot: "SlotAssignment") -> bytes:
    """SSE-frame one slot assignment as raw bytes.

    Wire shape::

        id: <seq>\\n
        event: slot\\n
        data: <id>|<x>|<y>|<kind>|<domain_id>\\n\\n

    Floats are formatted with one decimal place; at FILE_R = 220 px,
    sub-pixel precision is invisible and costs ~3-4 bytes/event.
    """
    _validate_id(slot.node_id, "slot.node_id")
    _validate_kind(slot.kind)
    _validate_id(slot.domain_id, "slot.domain_id")
    _validate_finite(slot.x, "slot.x")
    _validate_finite(slot.y, "slot.y")

    # Build the data payload as a single str then encode once.
    payload = f"{slot.node_id}|{slot.x:.1f}|{slot.y:.1f}|{slot.kind}|{slot.domain_id}"
    seq_bytes = str(seq).encode("ascii")
    data_bytes = payload.encode("utf-8")

    # Concatenation here is faster than b"".join for small fixed N on CPython.
    return _ID_PREFIX + seq_bytes + _NL + _EVT_SLOT + _DATA_PREFIX + data_bytes + _NLNL


def format_edge(seq: int, edge: "EdgeDelta") -> bytes:
    """SSE-frame one edge between two already-placed nodes."""
    _validate_id(edge.source_id, "edge.source_id")
    _validate_id(edge.target_id, "edge.target_id")
    _validate_kind(edge.kind)

    payload = f"{edge.source_id}|{edge.target_id}|{edge.kind}"
    seq_bytes = str(seq).encode("ascii")
    data_bytes = payload.encode("utf-8")

    return _ID_PREFIX + seq_bytes + _NL + _EVT_EDGE + _DATA_PREFIX + data_bytes + _NLNL


def format_done(seq: int, total_slots: int, total_edges: int) -> bytes:
    """Terminal frame; the renderer treats this as 'stop polling'."""
    if total_slots < 0 or total_edges < 0:
        raise ValueError("totals must be non-negative")
    payload = f"{total_slots}|{total_edges}".encode("ascii")
    seq_bytes = str(seq).encode("ascii")
    return _ID_PREFIX + seq_bytes + _NL + _EVT_DONE + _DATA_PREFIX + payload + _NLNL


def format_keepalive() -> bytes:
    """SSE comment line; clients ignore lines starting with ``:``."""
    return _KEEPALIVE


def format_terminator() -> bytes:
    """HTTP/1.1 chunked-transfer terminator for clean stream close."""
    return _CHUNK_TERM


def chunk_wrap(payload: bytes) -> bytes:
    """Wrap raw bytes in HTTP/1.1 chunked-transfer framing.

    ``<hex-len>\\r\\n<bytes>\\r\\n``. Empty payload is illegal here
    (use :func:`format_terminator` for the zero-length terminator).
    """
    if not payload:
        raise ValueError("chunk_wrap requires a non-empty payload")
    header = f"{len(payload):x}".encode("ascii")
    return header + _CRLF + payload + _CRLF


# --- decoders (test-only) ----------------------------------------------------


def parse_slot(data: bytes) -> tuple[str, float, float, str, str]:
    """Inverse of :func:`format_slot`'s data payload (no SSE framing).

    Browser clients call ``data.split('|')`` directly; this exists so the
    test suite can roundtrip-check the encoder.
    """
    parts = data.decode("utf-8").split("|")
    if len(parts) != 5:
        raise ValueError(f"slot data must have 5 fields, got {len(parts)}")
    node_id, x_s, y_s, kind, domain_id = parts
    return node_id, float(x_s), float(y_s), kind, domain_id


def parse_edge(data: bytes) -> tuple[str, str, str]:
    """Inverse of :func:`format_edge`'s data payload."""
    parts = data.decode("utf-8").split("|")
    if len(parts) != 3:
        raise ValueError(f"edge data must have 3 fields, got {len(parts)}")
    source_id, target_id, kind = parts
    return source_id, target_id, kind


# --- benchmark ---------------------------------------------------------------


def _benchmark(n: int = 1_000_000) -> tuple[float, float]:
    """Format ``n`` slot frames; return (MB/s, ns/event)."""
    import time
    from dataclasses import dataclass

    @dataclass(slots=True)
    class _Slot:
        node_id: str
        x: float
        y: float
        kind: str
        domain_id: str

    sample = _Slot(
        node_id="node_000123456",
        x=12345.6,
        y=-789.0,
        kind="function",
        domain_id="cortex_core_module",
    )

    total_bytes = 0
    start = time.perf_counter()
    for seq in range(n):
        # Mutate seq only; keeps payload size representative.
        frame = format_slot(seq, sample)
        total_bytes += len(frame)
    elapsed = time.perf_counter() - start

    mb_per_sec = (total_bytes / 1_048_576) / elapsed
    ns_per_event = (elapsed / n) * 1e9
    return mb_per_sec, ns_per_event


if __name__ == "__main__":
    n = 1_000_000
    mb_s, ns_evt = _benchmark(n)
    print(f"format_slot: {n:,} events")
    print(f"  throughput: {mb_s:7.2f} MB/s")
    print(f"  per-event:  {ns_evt:7.0f} ns")
