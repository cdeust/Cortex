"""Singleton connection pool for MCP clients — lazy connect, reuse, idle timeout.

Reads server config from mcp-connections.json, creates MCPClient instances on
demand, caches by server name.
"""

from __future__ import annotations

import os
import re
import sys

from mcp_server.infrastructure.upstream_identity import ALLOWED_UPSTREAM_COMMANDS
from typing import Any

from mcp_server.errors import McpConnectionError
from mcp_server.infrastructure.config import MCP_CONNECTIONS_PATH
from mcp_server.infrastructure.file_io import read_json
from mcp_server.infrastructure.mcp_client import MCPClient
from mcp_server.infrastructure.memory_config import get_memory_settings

# Insertion-ordered: dict preserves insertion order (PEP 468 / CPython 3.7+),
# so the FIRST key is the least-recently-used connection. ``get_client``
# re-inserts on every cache hit to keep this ordering an LRU ordering.
_pool: dict[str, MCPClient] = {}


def _load_server_config(server_name: str) -> dict[str, Any]:
    """Load server configuration from mcp-connections.json."""
    config = read_json(MCP_CONNECTIONS_PATH)
    if not config or not config.get("servers"):
        raise McpConnectionError(
            f"MCP connections config not found at {MCP_CONNECTIONS_PATH}. "
            f"Create it with server definitions.",
            {"path": str(MCP_CONNECTIONS_PATH)},
        )

    server_config = config["servers"].get(server_name)
    if not server_config:
        available = ", ".join(config["servers"].keys())
        raise McpConnectionError(
            f'Server "{server_name}" not found in MCP connections config. '
            f"Available: {available}",
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


def _evict_lru_idle() -> bool:
    """Evict the least-recently-used connection that is NOT serving a call.

    Pre-condition: the pool is at capacity and a new server is requested.
    Post-condition: returns True and removes exactly one connection (the
    LRU among connections with no in-flight request) if such a connection
    exists; returns False and mutates nothing if every live connection is
    busy. A busy connection is never evicted — closing it would cancel an
    in-flight request (see MCPClient.busy). Iteration order is insertion
    order, so the first non-busy key found is the LRU idle one.
    """
    for name, client in _pool.items():
        if not client.busy:
            client.close()
            del _pool[name]
            print(f'[mcp-pool] Evicted LRU idle "{name}" for capacity', file=sys.stderr)
            return True
    return False


def _admit_new_connection(server_name: str) -> None:
    """Bound the pool size before a new connection is opened.

    Pre-condition: ``server_name`` is not already a live pooled connection.
    Post-condition: the pool holds < max connections (room for one more),
    OR an McpConnectionError is raised. When at capacity, the LRU idle
    connection is evicted; if all are busy, fail fast rather than grow
    unbounded — this is the explicit anti-leak guarantee from the
    pool-leak fix follow-on. source: docs/provenance/bounded-io-plan.md Phase 3.
    """
    max_conns = get_memory_settings().mcp_pool_max_connections
    if len(_pool) < max_conns:
        return
    if _evict_lru_idle():
        return
    raise McpConnectionError(
        f"MCP connection pool exhausted: {len(_pool)}/{max_conns} live "
        f"connections are all busy; cannot open one for "
        f'"{server_name}". Retry after an in-flight call completes.',
        {"serverName": server_name, "poolSize": len(_pool), "max": max_conns},
    )


async def get_client(server_name: str) -> MCPClient:
    """Get a connected MCP client for the named server.

    Pool size is bounded by mcp_pool_max_connections: a cache hit touches
    the LRU ordering; a miss admits via _admit_new_connection (LRU-evict or
    fail-fast) before spawning a child, so the pool never grows unbounded.
    """
    existing = _pool.get(server_name)
    if existing and existing.connected:
        # LRU touch: move to the most-recently-used end of the ordering.
        _pool[server_name] = _pool.pop(server_name)
        return existing

    # Clean up stale entry
    if existing:
        existing.close()
        del _pool[server_name]

    _admit_new_connection(server_name)

    config = _load_server_config(server_name)
    client = MCPClient(config)

    # Upstream MCP servers ship binaries that are not in the default
    # allowlist. Mirror the extension that ap_bridge.py applies on its
    # bridge path so the pool path is not silently rejected. Without
    # this, ingest_codebase fails with "Command not in allowed list"
    # even when mcp-connections.json correctly points at the binary.
    # source: ap_bridge.py L226-L233 — same set, same reason.
    client._extra_allowed_commands = {"node", *ALLOWED_UPSTREAM_COMMANDS}

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
