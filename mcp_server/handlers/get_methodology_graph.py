"""Handler for the get_methodology_graph tool — graph data for visualization."""

from __future__ import annotations

from mcp_server.infrastructure.profile_store import load_profiles
from mcp_server.core.graph_builder import build_graph

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


async def handler(args: dict | None = None) -> dict:
    args = args or {}
    profiles = load_profiles()
    return build_graph(profiles, args.get("domain"))
