"""GET /api/graph/chain — Mermaid DAG of the causal/impact chain from a node.

Reuses the bounded entity-graph BFS from ``get_causal_chain`` (the
canonical traversal over ``store``) and renders the edges as Mermaid
``flowchart TD`` for the frontend chain-of-action panel. Layer: server/;
imports handlers/, returns via the shared response helper, never imports
core/ directly, and never raises — failures collapse to a valid body.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from mcp_server.handlers.get_causal_chain import (
    _bfs_entity_graph,
    _resolve_start_entity_by_name,
)
from mcp_server.server.http_standalone_response import send_json_ok

# type -> BFS direction. Mirrors get_causal_chain semantics:
# outgoing = downstream effects (impact), incoming = upstream causes
# (causal), both = full neighbourhood (call).
_TYPE_TO_DIRECTION = {"impact": "outgoing", "causal": "incoming", "call": "both"}

_DEPTH_DEFAULT = 4
_DEPTH_MAX = 8
_NODE_CAP = 150  # hard cap on rendered nodes/edges combined
_LABEL_MAX = 40


def _parse_params(raw_path: str) -> tuple[str, int, str]:
    """Extract (id, depth, direction) from the query string.

    Postcondition: depth in [1, _DEPTH_MAX]; direction is a valid BFS
    direction; id may be empty (caller handles as not-found).
    """
    qs = parse_qs(urlparse(raw_path).query)
    node_id = (qs.get("id", [""])[0] or "").strip()
    try:
        depth = int(qs.get("depth", [str(_DEPTH_DEFAULT)])[0])
    except (ValueError, TypeError):
        depth = _DEPTH_DEFAULT
    depth = max(1, min(depth, _DEPTH_MAX))
    chain_type = (qs.get("type", ["causal"])[0] or "causal").lower()
    direction = _TYPE_TO_DIRECTION.get(chain_type, "incoming")
    return node_id, depth, direction


def _sanitize(label: str) -> str:
    """Mermaid node label: truncate at _LABEL_MAX, neutralise quotes."""
    return (label or "")[:_LABEL_MAX].replace('"', "'")


def _build_mermaid(edges: list[dict]) -> tuple[str, int, int, int, bool]:
    """Render BFS edges as a Mermaid flowchart TD.

    Returns (mermaid_text, node_count, edge_count, depth_reached,
    truncated). Caps total distinct nodes + rendered edges at _NODE_CAP.
    Node IDs are sanitized to ``nd_<n>`` (alphanumeric only) so arbitrary
    entity names can never break Mermaid parsing.
    """
    node_ids: dict[int, str] = {}
    lines: list[str] = []
    depth_reached = 0
    truncated = False

    def _node_ref(entity_id: int, name: str, kind: str) -> str | None:
        if entity_id not in node_ids:
            if len(node_ids) >= _NODE_CAP:
                return None  # node budget exhausted
            ref = f"nd_{len(node_ids)}"
            node_ids[entity_id] = ref
            lines.append(f'  {ref}["{_sanitize(name)}\\n({_sanitize(kind)})"]')
        return node_ids[entity_id]

    for edge in edges:
        if len(lines) >= _NODE_CAP:
            truncated = True
            break
        src = _node_ref(edge["source_id"], edge["source_name"], edge["source_type"])
        tgt = _node_ref(edge["target_id"], edge["target_name"], edge["target_type"])
        if src is None or tgt is None:
            truncated = True
            break
        rel = _sanitize(edge.get("relationship_type", "rel"))
        lines.append(f"  {src} -->|{rel}| {tgt}")
        depth_reached = max(depth_reached, edge.get("depth", 0))

    header = "%% truncated at 150 nodes\n" if truncated else ""
    mermaid = header + "flowchart TD\n" + "\n".join(lines)
    edge_count = sum(1 for ln in lines if "-->" in ln)
    return mermaid, len(node_ids), edge_count, depth_reached, truncated


def _not_found_payload(seed: str) -> dict:
    return {
        "mermaid": 'flowchart TD\n  A["Not found"]',
        "node_count": 0,
        "edge_count": 0,
        "depth_reached": 0,
        "truncated": False,
        "seed": seed,
    }


def serve_graph_chain(handler, store) -> None:
    """GET /api/graph/chain?id=&depth=&type= — Mermaid causal/impact DAG.

    Never raises: any failure (bad params, store error, render error)
    resolves to a valid not-found JSON body so the panel degrades
    gracefully instead of hanging on a 500.
    """
    seed = ""
    try:
        seed, depth, direction = _parse_params(handler.path)
        if not seed:
            send_json_ok(handler, _not_found_payload(seed))
            return

        entity = _resolve_start_entity_by_name(seed, store)
        if not entity:
            send_json_ok(handler, _not_found_payload(seed))
            return

        edges = _bfs_entity_graph(
            start_entity_id=entity["id"],
            store=store,
            max_depth=depth,
            max_edges=_NODE_CAP,
            direction=direction,
            rel_filter=None,
        )
        mermaid, n_nodes, n_edges, depth_reached, truncated = _build_mermaid(edges)
        send_json_ok(
            handler,
            {
                "mermaid": mermaid,
                "node_count": n_nodes,
                "edge_count": n_edges,
                "depth_reached": depth_reached,
                "truncated": truncated,
                "seed": entity.get("name", seed),
            },
        )
    except Exception:
        # Contract: this function never raises. send_json_ok sets the CORS
        # header via _apply_cors_headers, so the not-found body carries the
        # same headers as the success path.
        send_json_ok(handler, _not_found_payload(seed))
