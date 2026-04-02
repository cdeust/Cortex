"""Handler for the get_methodology_graph tool — graph data for visualization."""

from __future__ import annotations

from mcp_server.core.graph_builder import build_graph
from mcp_server.infrastructure.profile_store import load_profiles

schema = {
    "description": "Returns methodology map as graph data for 3D visualization. <100ms.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "Filter to specific domain (optional)",
            },
        },
        "required": [],
    },
}


_MAX_NODES = 200
_MAX_EDGES = 500


async def handler(args: dict | None = None) -> dict:
    args = args or {}
    profiles = load_profiles()
    graph = build_graph(profiles, args.get("domain"))

    # Cap output size to prevent multi-megabyte responses
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    if len(nodes) > _MAX_NODES:
        # Keep highest-quality nodes
        nodes.sort(key=lambda n: n.get("quality", 0), reverse=True)
        graph["nodes"] = nodes[:_MAX_NODES]
        graph["truncated_nodes"] = len(nodes) - _MAX_NODES
    if len(edges) > _MAX_EDGES:
        edges.sort(key=lambda e: e.get("weight", 0), reverse=True)
        graph["edges"] = edges[:_MAX_EDGES]
        graph["truncated_edges"] = len(edges) - _MAX_EDGES

    return graph
