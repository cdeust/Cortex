"""GET /api/node/<id> — return the full node dict from the build cache.

The SSE slot stream carries only ``(node_id, x, y, kind, domain_id)``
(see ``layout_authority_wire.format_slot``). When the user hovers /
clicks a node the renderer needs the full provenance — file path,
parent file, color, label, symbol_type, etc. — that the build worker
stashed in the cumulative graph cache.

This is a lazy, server-side stash lookup: the cache already exists
(populated by ``_kick_background_build._merge``); we just expose it
keyed by node id. Out-of-band of the layout authority on purpose:
keeping the SSE byte stream tiny is the design (see jobs.md §1, §3).

Pre:
  - path is ``/api/node/<id>`` with id = everything after the prefix.
  - ``http_standalone_graph._graph_cache`` may be None (build hasn't
    started); we respond 404 in that case.
Post:
  - 200 + JSON node dict on hit.
  - 404 + JSON ``{"error": ...}`` on miss.
"""

from __future__ import annotations

import json
from urllib.parse import unquote

_PREFIX = "/api/node/"


def _lookup_node(node_id: str) -> dict | None:
    """Scan the cumulative cache for ``node_id``. None if no cache or
    no match. O(N) over current node count — acceptable because the
    UI calls this per hover, not per frame, and the alternative (a
    second indexed mirror) doubles the memory footprint of the cache.
    """
    from mcp_server.server import http_standalone_graph as _hsg

    cache = _hsg._graph_cache  # noqa: SLF001 — module-level stash
    if not cache or not cache.get("data"):
        return None
    for node in cache["data"].get("nodes", []):
        if node.get("id") == node_id:
            return node
    return None


def serve(handler, store) -> None:
    """GET /api/node/<id> — return the cached node or 404."""
    path = handler.path
    path_no_qs = path.split("?", 1)[0]
    if not path_no_qs.startswith(_PREFIX):
        body = json.dumps({"error": "bad_path"}).encode("utf-8")
        handler.send_response(400)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        try:
            handler.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        return

    node_id = unquote(path_no_qs[len(_PREFIX) :])
    node = _lookup_node(node_id)

    if node is None:
        body = json.dumps({"error": "not_found", "node_id": node_id}).encode("utf-8")
        handler.send_response(404)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        try:
            handler.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        return

    body = json.dumps(node, default=str).encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    # Per-node payload is small + cache-stable for the build's lifetime.
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
