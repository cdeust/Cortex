"""Read-side client for the live viz server's graph cache.

The ``query_workflow_graph`` MCP handler runs in the Cortex MCP server
process; the galaxy build runs in the standalone viz server process.
Before this client existed the handler REBUILT the whole workflow graph
on every tool call — a full PG reload per query, and a graph that could
diverge from what the browser shows (ecosystem finding 2026-06-12).

This module discovers the live viz instance via the registry file that
``mcp_server/server/viz_instance.py`` writes (``{pid, port,
started_at}`` at ``~/.cache/cortex/viz-server.json`` — the file format
is the contract between the two processes; this is the read side, that
module is the write side) and drains the full graph through the
paginated ``/api/graph/slice`` endpoint. Pages are bounded; the UNION
of pages is complete — never a lossy cap (user direction 2026-06-12).

The drained graph is memoised per ``phase_seq``: the viz build bumps
the sequence every time it publishes more nodes, so a repeat tool call
against an unchanged graph costs one small ``/api/graph/slice``
header probe instead of a multi-MB drain.
"""

from __future__ import annotations

import http.client
import json
import urllib.request
from pathlib import Path
from typing import Any

# One page of the slice drain. Matches the server-side default in
# ``get_graph_slice``; at the measured 143k-node galaxy this drains in
# 8 pages. Bounded per request, complete across requests.
_PAGE_LIMIT = 20_000

# Per-request socket timeout. The slice endpoint serves from the
# in-process cache (no PG work), so multi-second pages indicate a
# GIL-pinned build phase — waiting is correct, hanging forever is not.
_TIMEOUT_S = 30.0

_memo: dict[str, Any] = {"port": None, "phase_seq": None, "graph": None}


def _instance_path() -> Path:
    """Registry file location — mirror of ``viz_instance.instance_path``."""
    return Path.home() / ".cache" / "cortex" / "viz-server.json"


def _live_port() -> int | None:
    """Port of the registered viz instance, or ``None`` when absent.

    Liveness is proven by the HTTP fetch itself (``fetch_live_graph``
    returns ``None`` on connection failure) — no pid probing here, the
    pid belongs to another process tree.
    """
    try:
        data = json.loads(_instance_path().read_text())
        return int(data["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _get_json(port: int, path: str) -> dict | None:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}{path}", timeout=_TIMEOUT_S
        ) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError, http.client.HTTPException):
        return None


def fetch_live_graph() -> dict | None:
    """Full graph from the live viz server, or ``None`` when no live
    instance answers.

    Returns ``{"nodes": [...], "edges": [...], "meta": {"source":
    "live-cache", "phase_seq": int, "full_ready": bool}}`` with FULL
    node/edge records (the slice endpoint serves the cache, not the
    slim wire). Complete: pages are drained until ``done``.
    """
    port = _live_port()
    if port is None:
        return None

    head = _get_json(port, f"/api/graph/slice?offset=0&limit={_PAGE_LIMIT}")
    if head is None:
        return None

    if (
        _memo["port"] == port
        and _memo["phase_seq"] == head.get("phase_seq")
        and _memo["graph"] is not None
    ):
        return _memo["graph"]

    nodes: list = list(head.get("nodes", []))
    edges: list = list(head.get("edges", []))
    offset = _PAGE_LIMIT
    done = bool(head.get("done"))
    while not done:
        page = _get_json(port, f"/api/graph/slice?offset={offset}&limit={_PAGE_LIMIT}")
        if page is None:
            # A page failed mid-drain: a partial graph silently posing
            # as complete is exactly the failure mode this design
            # forbids — report no live graph and let the caller fall
            # back to the local build.
            return None
        nodes.extend(page.get("nodes", []))
        edges.extend(page.get("edges", []))
        offset += _PAGE_LIMIT
        done = bool(page.get("done"))

    graph = {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "source": "live-cache",
            "phase_seq": head.get("phase_seq"),
            "full_ready": bool(head.get("full_ready")),
        },
    }
    _memo.update(port=port, phase_seq=head.get("phase_seq"), graph=graph)
    return graph
