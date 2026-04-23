"""Handler for the get_methodology_graph tool — graph data for visualization."""

from __future__ import annotations

from mcp_server.core.graph_builder import build_graph
from mcp_server.infrastructure.profile_store import load_profiles
from mcp_server.handlers._tool_meta import READ_ONLY

schema = {
    "title": "Get methodology graph",
    "annotations": READ_ONLY,
    "description": (
        "Build the methodology map as JSON graph data {nodes, edges, "
        "meta} suitable for force-directed visualization. Nodes: "
        "domains, concepts, memories, entities. Edges: cross-domain "
        "bridges, co-activation strengths, semantic relationships. "
        "Output is capped (200 nodes / 500 edges, highest-quality first) "
        "so the payload stays embeddable in a single MCP response. Use "
        "this to feed a CUSTOM client visualizer. Distinct from "
        "`open_visualization` (launches the bundled browser UI on "
        "127.0.0.1:3458, no JSON returned), `list_domains` (text-only "
        "domain overview), and `get_causal_chain` (entity-graph BFS, "
        "not the unified methodology map). Read-only on profiles.json + "
        "memories. Latency <100ms. Returns {nodes, edges, meta, "
        "truncated_nodes?, truncated_edges?}."
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
