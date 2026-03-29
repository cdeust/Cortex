"""Singleton connection pool for MCP clients — lazy connect, reuse, idle timeout.

Reads server config from mcp-connections.json, creates MCPClient instances on
demand, caches by server name.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any

from mcp_server.errors import McpConnectionError
from mcp_server.infrastructure.config import MCP_CONNECTIONS_PATH
from mcp_server.infrastructure.file_io import read_json
from mcp_server.infrastructure.mcp_client import MCPClient

_pool: dict[str, MCPClient] = {}


def _load_server_config(server_name: str) -> dict[str, Any]:
    """Load server configuration from mcp-connections.json."""
    config = read_json(MCP_CONNECTIONS_PATH)
    if not config or not config.get("servers"):
        raise McpConnectionError(
            f"MCP connections config not found at {MCP_CONNECTIONS_PATH}. Create it with server definitions.",
            {"path": str(MCP_CONNECTIONS_PATH)},
        )

    server_config = config["servers"].get(server_name)
    if not server_config:
        available = ", ".join(config["servers"].keys())
        raise McpConnectionError(
            f'Server "{server_name}" not found in MCP connections config. Available: {available}',
            {"serverName": server_name, "available": list(config["servers"].keys())},
        )

    # Resolve ${VAR} references in env block
    env = server_config.get("env")
    if env:
        for key, val in env.items():
            if isinstance(val, str):
                env[key] = re.sub(
                    r"\$\{(\w+)\}",
                    lambda m: os.environ.get(m.group(1), ""),
                    val,
                )

    return server_config


async def get_client(server_name: str) -> MCPClient:
    """Get a connected MCP client for the named server."""
    existing = _pool.get(server_name)
    if existing and existing.connected:
        return existing

    # Clean up stale entry
    if existing:
        existing.close()
        del _pool[server_name]

    config = _load_server_config(server_name)
    client = MCPClient(config)

    await client.connect()
    _pool[server_name] = client

    print(
        f'[mcp-pool] Connected to "{server_name}" '
        f"({len(client.list_tools())} tools, protocol {client.protocol_version})",
        file=sys.stderr,
    )

    return client


def close_client(server_name: str) -> None:
    """Close a specific client connection."""
    client = _pool.get(server_name)
    if client:
        client.close()
        del _pool[server_name]
        print(f'[mcp-pool] Closed "{server_name}"', file=sys.stderr)


def close_all() -> None:
    """Close all client connections. Safe for shutdown hooks."""
    for name, client in list(_pool.items()):
        client.close()
        print(f'[mcp-pool] Closed "{name}"', file=sys.stderr)
    _pool.clear()
