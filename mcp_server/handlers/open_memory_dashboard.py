"""Handler: open_memory_dashboard — launch memory visualization in browser."""

from __future__ import annotations

from mcp_server.server.http_launcher import launch_server, open_in_browser

schema = {
    "description": "Launch the real-time memory dashboard in the browser. Shows heat map, entity graph, activity feed, and system stats.",
    "inputSchema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


async def handler(args: dict | None = None) -> dict:
    url = launch_server("dashboard")
    open_in_browser(url)

    return {
        "url": url,
        "message": f"Memory dashboard opened at {url}",
    }
