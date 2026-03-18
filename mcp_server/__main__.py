"""Bootstrap entry point for the methodology-agent MCP server.

Uses FastMCP (3.x) for protocol handling — supports MCP 2025-11-25 natively.
Bridges existing async handler functions as FastMCP tools.

Usage:
    python -m mcp_server
"""

from __future__ import annotations

import signal
import sys

from fastmcp import FastMCP

from mcp_server.infrastructure.mcp_client_pool import close_all
from mcp_server.server.http_server import shutdown_server
from mcp_server.server.http_dashboard_server import shutdown_memory_dashboard_server
from mcp_server.server.http_viz_server import shutdown_unified_viz_server
from mcp_server import tool_registry_core
from mcp_server import tool_registry_memory
from mcp_server import tool_registry_manage
from mcp_server import tool_registry_nav
from mcp_server import tool_registry_advanced

# ── Server Instance ────────────────────────────────────────────────────────

mcp = FastMCP(
    name="methodology-agent",
    version="1.0.0",
    instructions=(
        "JARVIS cognitive profiling system for Claude Code. "
        "Extracts reasoning signatures from session history and pre-loads them at session start. "
        "Call query_methodology at the beginning of every session. "
        "Use remember/recall for persistent thermodynamic memory across sessions."
    ),
)

# ── Tool Registration ──────────────────────────────────────────────────────

tool_registry_core.register(mcp)
tool_registry_memory.register(mcp)
tool_registry_manage.register(mcp)
tool_registry_nav.register(mcp)
tool_registry_advanced.register(mcp)

# ── Lifecycle ──────────────────────────────────────────────────────────────


def _shutdown(sig=None, frame=None) -> None:
    close_all()
    shutdown_server()
    shutdown_memory_dashboard_server()
    shutdown_unified_viz_server()
    sys.exit(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
