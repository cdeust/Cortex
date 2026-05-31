"""SSE handler for the live layout-authority slot/edge stream.

The build worker emits ``(seq, kind, payload_bytes)`` tuples via
``layout_authority._log``. ``payload_bytes`` is already SSE-formatted by
``layout_authority_wire`` (``id: <seq>\\nevent: <kind>\\ndata: ...\\n\\n``).
This handler:

* opens the SSE stream (HTTP/1.1 chunked, Last-Event-ID resume — best
  effort, see invariant I3 in ``layout_authority_log.reset``),
* drains its subscriber queue, wraps each payload in a chunked-transfer
  frame, writes it to the socket,
* sends a ``: ping\\n\\n`` keepalive every 15 s of silence so proxies
  don't tear down idle connections,
* terminates cleanly when the ``done`` event arrives or the client
  disconnects (BrokenPipe / ConnectionReset / OSError),
* unsubscribes its queue under any termination path.

Composition root: ``http_standalone._route_unified_get`` wires this in.
The handler depends only on ``server.http_standalone_graph`` (for the
lazy authority singleton) and the ``layout_authority_log`` / ``_wire``
modules (for stats and the keepalive bytes).
"""

from __future__ import annotations

import json
import queue as _queue_mod

from mcp_server.server import layout_authority_log as _log
from mcp_server.server import layout_authority_wire as _wire

_KEEPALIVE_TIMEOUT_S = 15.0


def _write_chunk(handler, payload: bytes) -> bool:
    """Write one HTTP/1.1 chunked frame. Return False on socket error."""
    try:
        frame = _wire.chunk_wrap(payload)
        handler.wfile.write(frame)
        handler.wfile.flush()
        return True
    except (BrokenPipeError, ConnectionResetError, OSError):
        return False


def _write_terminator(handler) -> None:
    try:
        handler.wfile.write(_wire.format_terminator())
        handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass


def serve(handler, store) -> None:
    """SSE handler — subscribe, drain, write chunks until done/disconnect.

    Pre:
      - handler is a BaseHTTPRequestHandler with HTTP/1.1 protocol_version.
    Post:
      - subscriber queue is unsubscribed regardless of termination path.
    """
    # Lazy import — avoids a circular at module load.
    from mcp_server.server.http_standalone_graph import get_layout_authority

    authority = get_layout_authority()

    # SSE headers. ``X-Accel-Buffering: no`` defeats nginx/cloudflare
    # response buffering. Transfer-Encoding chunked is implied by HTTP/1.1
    # without Content-Length but we set it explicitly for clarity.
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache, no-transform")
    handler.send_header("X-Accel-Buffering", "no")
    handler.send_header("Connection", "keep-alive")
    handler.send_header("Transfer-Encoding", "chunked")
    handler.end_headers()

    q = authority.subscribe()
    try:
        while True:
            try:
                seq, kind, payload = q.get(timeout=_KEEPALIVE_TIMEOUT_S)
            except _queue_mod.Empty:
                # Keepalive — payload is a non-empty SSE comment.
                if not _write_chunk(handler, _wire.format_keepalive()):
                    return
                continue

            if not _write_chunk(handler, payload):
                return

            if kind == "done":
                _write_terminator(handler)
                return
    finally:
        authority.unsubscribe(q)


def serve_stats(handler, store) -> None:
    """GET /api/graph/stream/stats — JSON of log + authority counters.

    Returns ``{"log": <log.stats()>, "authority": <authority.stats()>}``
    so dashboards can verify the producer is making progress and no
    subscriber backlog is growing.
    """
    from mcp_server.server.http_standalone_graph import get_layout_authority

    authority = get_layout_authority()
    payload = {
        "log": _log.stats(),
        "authority": authority.stats(),
    }
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
