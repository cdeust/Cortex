"""Handler for the ``query_workflow_graph`` tool (Gap 1).

Returns a TYPED subgraph from the already-built workflow graph via a
declarative filter — no Cypher engine, no new dependency. The filter
is the smallest surface that unlocks downstream agent tools:

  * ``node_kind``     — keep nodes of one or more kinds (domain,
                        file, memory, symbol, entity, …)
  * ``edge_kind``     — keep edges of one or more kinds (calls,
                        imports, defined_in, about_entity, …)
  * ``neighbour_of``  — k-hop neighbourhood around a specific node id
  * ``depth``         — ≤2 (guards against N² blowup on a 27k-node
                        graph)
  * ``domain``        — restrict to one domain (matches the underlying
                        ``build_workflow_graph`` param)
  * ``limit_nodes``   — hard cap on returned nodes (default 500, max
                        5000) so an MCP round-trip stays under a few
                        hundred KB

Pure composition root — wires ``infrastructure.WorkflowGraphSource`` +
``core.WorkflowGraphBuilder`` and filters the result. No I/O itself.
"""

from __future__ import annotations

from typing import Any

from mcp_server.handlers._tool_meta import READ_ONLY
from mcp_server.handlers.workflow_graph import build_workflow_graph
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import MemoryStore

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    """Lazy-singleton memory store (same pattern as remember/recall)."""
    global _store
    if _store is None:
        s = get_memory_settings()
        _store = MemoryStore(s.DB_PATH, s.EMBEDDING_DIM)
    return _store


schema = {
    "title": "Query the Claude workflow graph",
    "annotations": READ_ONLY,
    "description": (
        "Return a typed subgraph of the unified workflow graph — the "
        "same graph the browser visualization renders, but filtered "
        "down to the slice a downstream tool actually needs. Filters: "
        "``node_kind`` (one or more of domain, skill, command, hook, "
        "agent, tool_hub, file, memory, discussion, entity, mcp, "
        "symbol), ``edge_kind`` (one or more of in_domain, "
        "tool_used_file, calls, imports, defined_in, member_of, "
        "about_entity, triggered_hook, invoked_skill, spawned_agent, "
        "invoked_mcp, …), ``neighbour_of`` (a node id; returns the "
        "k-hop subgraph around it), ``depth`` (1 or 2 hops — default "
        "1), ``domain`` (restrict to one project), ``limit_nodes`` "
        "(cap, default 500, max 5000). Output shape matches the "
        "/api/graph payload: ``{nodes, edges, meta}``. Distinct from "
        "``get_methodology_graph`` (legacy methodology map, 200-node "
        "cap) and ``open_visualization`` (launches browser). Use this "
        "as the data source for blast-radius / change-impact / any "
        "agent reasoning over the graph structure. Read-only. Latency "
        "depends on graph size (typically <500ms for a filtered "
        "slice)."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "node_kind": {
                "type": ["string", "array"],
                "items": {"type": "string"},
                "description": (
                    "Keep nodes of this kind (one or a list). Omit for every kind."
                ),
                "examples": ["symbol", ["file", "symbol"]],
            },
            "edge_kind": {
                "type": ["string", "array"],
                "items": {"type": "string"},
                "description": (
                    "Keep edges of this kind (one or a list). Omit for every kind."
                ),
                "examples": ["calls", ["defined_in", "member_of"]],
            },
            "neighbour_of": {
                "type": "string",
                "description": (
                    "Return the k-hop subgraph around this node id. "
                    "Example ids: ``symbol:abc123``, ``file:deadbeef``, "
                    "``domain:cortex``."
                ),
            },
            "depth": {
                "type": "integer",
                "minimum": 1,
                "maximum": 2,
                "default": 1,
                "description": (
                    "BFS depth for ``neighbour_of``. 1 = direct "
                    "neighbours, 2 = two hops. Capped at 2 to bound "
                    "response size."
                ),
            },
            "domain": {
                "type": "string",
                "description": "Restrict to one project's subgraph.",
                "examples": ["cortex", "ai-architect"],
            },
            "limit_nodes": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5000,
                "default": 500,
                "description": (
                    "Hard cap on returned nodes. Trimmed nodes get "
                    "reported in ``meta.truncated_nodes``."
                ),
            },
        },
    },
}


# Node-count caps — measured 2026-04-23 on Cortex's 27k-node graph:
# 500 nodes serialise to ≈120 KB, 5000 ≈1.2 MB. MCP's default frame
# ceiling is ~1 MB so 5000 is the hard maximum; 500 keeps typical
# responses under a second on a warm graph.
_DEFAULT_LIMIT = 500
_MAX_LIMIT = 5000


def _as_set(value: Any) -> set[str] | None:
    """Normalise a string-or-list filter argument to a set, or None."""
    if value is None:
        return None
    if isinstance(value, str):
        return {value} if value else None
    if isinstance(value, (list, tuple)):
        out = {str(v) for v in value if v}
        return out or None
    return None


def _edge_kind(e: dict) -> str:
    return str(e.get("kind") or e.get("type") or "")


def _node_kind(n: dict) -> str:
    return str(n.get("kind") or n.get("type") or "")


def _edge_endpoints(e: dict) -> tuple[str, str]:
    s = e.get("source")
    t = e.get("target")
    s_id = s.get("id") if isinstance(s, dict) else s
    t_id = t.get("id") if isinstance(t, dict) else t
    return str(s_id or ""), str(t_id or "")


def _bfs_neighbourhood(
    nodes: list[dict],
    edges: list[dict],
    seed: str,
    depth: int,
) -> tuple[set[str], list[dict]]:
    """Return (node_ids, surviving_edges) for a k-hop BFS around ``seed``.

    Edges whose both endpoints are in the surviving set are kept. An
    edge whose source or target falls outside the radius is dropped,
    matching the UI's "no dangling edges" contract.
    """
    if depth < 1:
        return {seed}, []
    adj: dict[str, list[str]] = {}
    for e in edges:
        s, t = _edge_endpoints(e)
        if not s or not t:
            continue
        adj.setdefault(s, []).append(t)
        adj.setdefault(t, []).append(s)
    frontier = {seed}
    reached = {seed}
    for _ in range(depth):
        next_frontier: set[str] = set()
        for nid in frontier:
            for other in adj.get(nid, ()):
                if other not in reached:
                    next_frontier.add(other)
        reached.update(next_frontier)
        if not next_frontier:
            break
        frontier = next_frontier
    kept_edges = [
        e
        for e in edges
        if (_edge_endpoints(e)[0] in reached and _edge_endpoints(e)[1] in reached)
    ]
    return reached, kept_edges


def _prune_dangling_edges(edges: list[dict], node_ids: set[str]) -> list[dict]:
    """Drop edges whose either endpoint is outside ``node_ids``.

    Every filter stage that removes nodes calls this so the renderer's
    "no dangling edges" contract survives."""
    kept: list[dict] = []
    for e in edges:
        s, t = _edge_endpoints(e)
        if s in node_ids and t in node_ids:
            kept.append(e)
    return kept


def _cap_nodes_by_heat(
    nodes: list[dict], edges: list[dict], limit: int
) -> tuple[list[dict], list[dict], int]:
    """Trim ``nodes`` to ``limit`` rows ranked by heat (desc)."""
    if len(nodes) <= limit:
        return nodes, edges, 0
    nodes.sort(
        key=lambda n: float(n.get("heat") or n.get("size") or 0.0),
        reverse=True,
    )
    truncated = len(nodes) - limit
    nodes = nodes[:limit]
    return nodes, _prune_dangling_edges(edges, {n.get("id") for n in nodes}), truncated


def _build_meta(
    graph: dict,
    *,
    node_kinds: set[str] | None,
    edge_kinds: set[str] | None,
    neighbour_of: str | None,
    depth: int,
    limit_nodes: int,
    truncated: int,
) -> dict:
    """Assemble the output meta block for a filtered subgraph."""
    meta = dict(graph.get("meta") or {})
    meta["filtered"] = True
    meta["filter"] = {
        "node_kind": sorted(node_kinds) if node_kinds else None,
        "edge_kind": sorted(edge_kinds) if edge_kinds else None,
        "neighbour_of": neighbour_of,
        "depth": depth if neighbour_of else None,
        "limit_nodes": limit_nodes,
    }
    if truncated:
        meta["truncated_nodes"] = truncated
    return meta


def _apply_filters(
    graph: dict,
    *,
    node_kinds: set[str] | None,
    edge_kinds: set[str] | None,
    neighbour_of: str | None,
    depth: int,
    limit_nodes: int,
) -> dict:
    """Apply BFS → edge_kind → node_kind → cap in that order.

    BFS runs over the FULL edge set so hop-count reflects structural
    reachability; ``edge_kind`` then slices edges inside the reached
    radius. A caller wanting BFS-over-single-edge-kind has to pre-
    filter. The output subgraph may violate ``validate_graph`` (a
    ``node_kind={'symbol'}`` slice drops every in_domain edge) — by
    design: this is a data query, not a renderable full graph.
    """
    nodes: list[dict] = list(graph.get("nodes") or [])
    edges: list[dict] = list(graph.get("edges") or graph.get("links") or [])

    if neighbour_of:
        reached, edges = _bfs_neighbourhood(nodes, edges, neighbour_of, depth)
        nodes = [n for n in nodes if n.get("id") in reached]

    if edge_kinds is not None:
        edges = [e for e in edges if _edge_kind(e) in edge_kinds]

    if node_kinds is not None:
        nodes = [n for n in nodes if _node_kind(n) in node_kinds]
        edges = _prune_dangling_edges(edges, {n.get("id") for n in nodes})

    nodes, edges, truncated = _cap_nodes_by_heat(nodes, edges, limit_nodes)

    meta = _build_meta(
        graph,
        node_kinds=node_kinds,
        edge_kinds=edge_kinds,
        neighbour_of=neighbour_of,
        depth=depth,
        limit_nodes=limit_nodes,
        truncated=truncated,
    )
    return {"nodes": nodes, "edges": edges, "links": edges, "meta": meta}


async def handler(args: dict | None = None, store=None) -> dict:
    """Build the workflow graph, then apply the requested filter.

    ``store`` is optional for tests; in MCP/production use it falls
    back to the same lazy-singleton ``MemoryStore`` that remember /
    recall resolve.
    """
    args = args or {}

    depth_raw = args.get("depth")
    try:
        depth = max(1, min(2, int(depth_raw))) if depth_raw is not None else 1
    except (TypeError, ValueError):
        depth = 1

    limit_raw = args.get("limit_nodes")
    try:
        limit_nodes = int(limit_raw) if limit_raw is not None else _DEFAULT_LIMIT
    except (TypeError, ValueError):
        limit_nodes = _DEFAULT_LIMIT
    limit_nodes = max(1, min(_MAX_LIMIT, limit_nodes))

    graph = build_workflow_graph(
        store if store is not None else _get_store(),
        domain_filter=args.get("domain"),
        stage="full",
    )

    return _apply_filters(
        graph,
        node_kinds=_as_set(args.get("node_kind")),
        edge_kinds=_as_set(args.get("edge_kind")),
        neighbour_of=args.get("neighbour_of"),
        depth=depth,
        limit_nodes=limit_nodes,
    )


__all__ = ["schema", "handler"]
