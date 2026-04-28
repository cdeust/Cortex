"""POST /api/recompute_layout — orchestrate the layout pipeline.

Composition root: pulls the cached graph from the standalone server's
in-memory cache, asks ``core.layout_engine`` to compute (x, y), and
persists the result via ``infrastructure.layout_pg_store``.

The handler is synchronous in v1 — at 1M nodes a DrL pass takes
roughly 90 s on an M-series Mac, ~3 min on older Intel. We surface
that as a long HTTP request rather than introducing background-job
infrastructure for the first cut. PR 2 will move the run off the
request thread.
"""

from __future__ import annotations

import json
import time
from typing import Any


def _extract_topology(graph_data: dict) -> tuple[list[str], list[tuple], dict]:
    """Pull ids + edges + kind map out of the cached /api/graph payload.

    The cached graph stores edges with ``source`` / ``target`` as raw
    string ids (the server's internal shape). We tolerate the
    object-form too in case a builder leaves the resolved references
    in place.
    """
    nodes_in = graph_data.get("nodes") or []
    edges_in = graph_data.get("edges") or []
    node_ids = [n["id"] for n in nodes_in if n.get("id")]
    kinds = {n["id"]: (n.get("kind") or "unknown") for n in nodes_in if n.get("id")}
    edges: list[tuple[str, str]] = []
    for e in edges_in:
        s = e.get("source")
        t = e.get("target")
        if isinstance(s, dict):
            s = s.get("id")
        if isinstance(t, dict):
            t = t.get("id")
        if s and t and s != t:
            edges.append((s, t))
    return node_ids, edges, kinds


def run_recompute(store) -> dict[str, Any]:
    """Run the layout pass against the currently-cached graph.

    Returns a JSON-serialisable status dict:
        {
          "status": "ok",
          "node_count": N,
          "edge_count": E,
          "elapsed_ms": M,
          "topology_fingerprint": "abc123...",
          "layout_version": 1730212345678,
        }

    Or:
        {"status": "error", "reason": "no_graph_cached"}
        {"status": "error", "reason": "igraph_missing"}
    """
    # Pull the cached graph from the in-memory builder. Avoiding a
    # core→server import: we reach into ``http_standalone_graph``
    # directly because that module owns the cache lifecycle.
    from mcp_server.server import http_standalone_graph as _gb

    if not _gb._graph_cache or not _gb._graph_cache.get("data"):
        return {"status": "error", "reason": "no_graph_cached"}
    graph_data = _gb._graph_cache["data"]
    node_ids, edges, kinds = _extract_topology(graph_data)
    if not node_ids:
        return {"status": "error", "reason": "empty_graph"}

    from mcp_server.core import layout_engine
    from mcp_server.infrastructure import layout_pg_store

    fp = layout_engine.topology_fingerprint(node_ids, edges)
    started = time.monotonic()
    try:
        coords = layout_engine.layout(node_ids, edges)
    except ImportError as exc:
        return {"status": "error", "reason": "igraph_missing", "detail": str(exc)}
    layout_version = layout_pg_store.write_layout(
        store, coords, kinds, topology_fingerprint=fp
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    return {
        "status": "ok",
        "node_count": len(node_ids),
        "edge_count": len(edges),
        "elapsed_ms": elapsed_ms,
        "topology_fingerprint": fp,
        "layout_version": layout_version,
    }


def serve(handler, store) -> None:
    """HTTP route adapter — wires ``run_recompute`` into the standalone server."""
    try:
        result = run_recompute(store)
    except Exception as exc:  # pragma: no cover
        result = {"status": "error", "reason": "exception", "detail": str(exc)}
    body = json.dumps(result).encode("utf-8")
    handler.send_response(200 if result.get("status") == "ok" else 503)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
