"""Handler for the get_methodology_graph tool — graph data for visualization."""

from __future__ import annotations

from mcp_server.core.graph_builder import build_graph
from mcp_server.infrastructure.profile_store import load_profiles

schema = {
    "description": (
        "Return the methodology map as JSON graph data {nodes, edges, meta} "
        "suitable for force-directed visualization. Nodes include domains, "
        "concepts, memories, and entities; edges encode bridges, co-activation, "
        "and semantic relationships. Output is capped (200 nodes / 500 edges, "
        "highest-quality first) so the payload stays embeddable in a single "
        "MCP response. Use this to feed a custom client visualizer; for the "
        "built-in browser UI use open_visualization. Sub-100ms."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "domain": {
                "type": "string",
                "description": "Restrict the graph to a single cognitive domain. Omit for the full cross-domain graph.",
                "examples": ["cortex", "auth-service"],
            },
        },
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
