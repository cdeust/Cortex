"""Handler for the open_visualization tool — launches unified 3D graph in browser."""

from __future__ import annotations

from mcp_server.server.http_launcher import launch_server, open_in_browser

schema = {
    "description": "Launch the unified 3D neural graph in the browser. Combines methodology profiles, memories, and knowledge graph.",
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
    url = launch_server("unified")
    open_in_browser(url)

    return {
        "url": url,
        "message": f"Unified neural graph opened at {url}",
    }
