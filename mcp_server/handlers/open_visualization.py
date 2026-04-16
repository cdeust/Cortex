"""Handler for the open_visualization tool — launches unified 3D graph in browser."""

from __future__ import annotations

from mcp_server.server.http_launcher import launch_server, open_in_browser

schema = {
    "description": (
        "Open the bundled Cortex visualization in the user's default "
        "browser — a force-directed neural graph combining methodology "
        "profiles, memory nodes, and the knowledge graph, plus the Wiki, "
        "Atlas, Emotion, Board, Pipeline, and Knowledge views. Starts "
        "the local HTTP server on 127.0.0.1:3458 if not already running "
        "and auto-shuts-down after 10 minutes of idle. Use this for "
        "visual exploration, screenshots, or presenting Cortex state. "
        "Distinct from `get_methodology_graph` (returns JSON for a "
        "CUSTOM client, no browser launched, no auxiliary views) and "
        "`list_domains` (text overview, no graph). Side effects: spawns "
        "an HTTP server process and opens a browser tab. Latency ~200ms "
        "(server warmup + browser launch). Returns {url, message}."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "domain": {
                "type": "string",
                "description": (
                    "Restrict the initial graph view to a single cognitive "
                    "domain. Omit to show the full graph (all domains visible)."
                ),
                "examples": ["cortex", "auth-service"],
            },
        },
    },
}


async def handler(args: dict | None = None) -> dict:
    url = launch_server("unified")
    open_in_browser(url)

    return {
        "url": url,
        "message": f"Unified neural graph opened at {url}",
    }
