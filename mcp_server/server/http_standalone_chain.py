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

# ── Structural node kinds that live in the workflow graph, not PG entities ──
# For these we BFS the in-memory workflow graph cache instead.
_STRUCTURAL_KINDS = frozenset(
    {"skill", "hook", "command", "agent", "mcp", "tool_hub", "file", "symbol"}
)


def _wfg_chain(node_id: str, depth: int) -> dict:
    """BFS over the in-memory workflow graph cache from ``node_id``.

    Returns a Mermaid payload shaped like the PG-entity path so the
    chain panel renders identically regardless of which path resolved.
    """
    try:
        from mcp_server.server.http_standalone_graph import _graph_cache  # type: ignore
    except ImportError:
        return _not_found_payload(node_id)

    cache = _graph_cache
    if not cache:
        return _not_found_payload(node_id)

    nodes_raw = cache.get("nodes") or []
    edges_raw = cache.get("edges") or []

    id_to_node: dict[str, dict] = {
        n["id"]: n for n in nodes_raw if n.get("id")
    }
    if node_id not in id_to_node:
        return _not_found_payload(node_id)

    # Build adjacency (undirected for "call"; can refine per direction later)
    adj: dict[str, list[dict]] = {}
    for e in edges_raw:
        s, t = e.get("source", ""), e.get("target", "")
        if s and t:
            adj.setdefault(s, []).append(e)
            adj.setdefault(t, []).append(e)

    # BFS bounded by depth and _NODE_CAP
    GOLDEN = 2.39996322972865332
    visited: set[str] = {node_id}
    frontier = [node_id]
    edges_out: list[dict] = []
    node_idx: dict[str, str] = {}

    def _ref(nid: str) -> str:
        if nid not in node_idx:
            n = id_to_node.get(nid, {})
            lbl = (n.get("label") or n.get("name") or nid).split("/")[-1][:32]
            kind = n.get("kind") or n.get("type") or "node"
            ref = f"nd_{len(node_idx)}"
            node_idx[nid] = ref
            return f'  {ref}["{lbl}\\n({kind})"]'
        return ""

    lines: list[str] = []
    for _ in range(depth):
        if not frontier or len(lines) >= _NODE_CAP:
            break
        next_front: list[str] = []
        for nid in frontier:
            for e in adj.get(nid, []):
                s, t = e.get("source", ""), e.get("target", "")
                nbr = t if s == nid else s
                src_node = id_to_node.get(s, {})
                tgt_node = id_to_node.get(t, {})
                decl_s = _ref(s)
                decl_t = _ref(t)
                if decl_s:
                    lines.append(decl_s)
                if decl_t:
                    lines.append(decl_t)
                rel = (e.get("kind") or e.get("type") or "link")[:20]
                lines.append(f"  {node_idx[s]} -->|{rel}| {node_idx[t]}")
                if nbr not in visited:
                    visited.add(nbr)
                    next_front.append(nbr)
                if len(lines) >= _NODE_CAP:
                    break
        frontier = next_front

    if not node_idx:
        return _not_found_payload(node_id)

    seed_node = id_to_node.get(node_id, {})
    seed_label = (seed_node.get("label") or node_id).split(":")[-1]
    n_nodes = len(node_idx)
    n_edges = sum(1 for ln in lines if "-->" in ln)
    truncated = len(lines) >= _NODE_CAP
    header = "%% truncated\n" if truncated else ""
    mermaid = header + "flowchart TD\n" + "\n".join(lines)
    return {
        "mermaid": mermaid,
        "node_count": n_nodes,
        "edge_count": n_edges,
        "depth_reached": depth,
        "truncated": truncated,
        "seed": seed_label,
    }

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

        # ── Resolve seed to one or more entity start IDs ──────────────────
        # Three node-id schemas from the workflow graph:
        #   entity:<pgid>  → PG entity by primary key (direct)
        #   domain:<slug>  → top entities in that domain (aggregate)
        #   <other>        → strip prefix, try name lookup
        start_entities: list[dict] = []
        resolved_seed = seed

        if seed.startswith("entity:"):
            raw_id = seed[len("entity:"):]
            try:
                ent = store.get_entity_by_id(int(raw_id))
                if ent:
                    start_entities = [ent]
                    resolved_seed = ent.get("name", seed)
            except (ValueError, TypeError):
                pass

        elif seed.startswith("domain:"):
            slug = seed[len("domain:"):]
            start_entities = store.get_top_entities_for_domain(slug, limit=15)
            resolved_seed = slug

        else:
            # Check if this is a structural node kind (skill, hook, file, etc.)
            # by looking at the prefix; if so, go straight to wfg BFS.
            prefix = seed.split(":")[0] if ":" in seed else ""
            if prefix in _STRUCTURAL_KINDS:
                send_json_ok(handler, _wfg_chain(seed, depth))
                return

            # Otherwise try entity name lookup (symbol / technology / concept).
            bare = seed.split(":")[-1] if ":" in seed else seed
            ent = _resolve_start_entity_by_name(bare, store)
            if not ent and bare != seed:
                ent = _resolve_start_entity_by_name(seed, store)
            if ent:
                start_entities = [ent]
                resolved_seed = ent.get("name", seed)

        if not start_entities:
            # Last resort: try workflow graph BFS for any unresolved id
            wfg = _wfg_chain(seed, depth)
            if wfg.get("node_count", 0) > 0:
                send_json_ok(handler, wfg)
                return
            send_json_ok(handler, _not_found_payload(seed))
            return

        # ── BFS from each start entity, merge ─────────────────────────────
        all_edges: list[dict] = []
        cap_per = max(1, _NODE_CAP // len(start_entities))
        for ent in start_entities:
            all_edges.extend(
                _bfs_entity_graph(
                    start_entity_id=ent["id"],
                    store=store,
                    max_depth=depth,
                    max_edges=cap_per,
                    direction=direction,
                    rel_filter=None,
                )
            )
            if len(all_edges) >= _NODE_CAP:
                break

        mermaid, n_nodes, n_edges, depth_reached, truncated = _build_mermaid(all_edges)
        send_json_ok(
            handler,
            {
                "mermaid": mermaid,
                "node_count": n_nodes,
                "edge_count": n_edges,
                "depth_reached": depth_reached,
                "truncated": truncated,
                "seed": resolved_seed,
            },
        )
    except Exception:
        send_json_ok(handler, _not_found_payload(seed))
