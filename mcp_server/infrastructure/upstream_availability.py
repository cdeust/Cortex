"""Detect whether upstream MCP integrations are reachable.

Gates the registration of the three upstream-dependent tools
(``ingest_codebase`` + ``change_impact`` → ai-architect-mcp-codebase; ``ingest_prd``
→ prd-spec-generator). On a standalone install with no upstream configured,
these tools do not register — so every advertised tool works out of the box.

source: Anthropic MCP Directory submission decision 2026-06-19 — the bundle
presents 43 standalone tools; the 3 upstream-integration tools auto-register
only when their upstream MCP server is actually present (mcp-connections.json
entry, marketplace plugin, PATH binary, or sibling checkout).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from mcp_server.infrastructure.config import MCP_CONNECTIONS_PATH
from mcp_server.infrastructure.file_io import read_json


def _server_command_runnable(server_name: str) -> bool:
    """True when mcp-connections.json wires ``server_name`` to a runnable command.

    A path-form command must exist and be executable; a bare command name must
    resolve on PATH. A configured-but-broken entry reads as unavailable so the
    gated tool is not advertised when it could only fail.
    """
    config = read_json(MCP_CONNECTIONS_PATH) or {}
    server = (config.get("servers") or {}).get(server_name)
    if not isinstance(server, dict):
        return False
    command = server.get("command")
    if not command:
        return False
    if "/" in str(command):
        path = Path(str(command)).expanduser()
        return path.is_file() and os.access(path, os.X_OK)
    return shutil.which(str(command)) is not None


def codebase_upstream_available() -> bool:
    """True when the ai-architect-mcp-codebase (``codebase``) MCP server is reachable.

    Either explicitly wired in mcp-connections.json, or discoverable via the
    marketplace plugin / PATH binary / sibling source checkout.
    """
    if _server_command_runnable("codebase"):
        return True
    # Lazy import: pipeline_discovery is infra-internal and heavier than this
    # module; importing at call time keeps the gate cheap when already wired.
    from mcp_server.infrastructure.pipeline_discovery import (  # noqa: PLC0415 — documented deferral: pipeline_discovery is heavier than this module; the gate stays cheap when already wired
        discover_pipeline_command,
    )

    return discover_pipeline_command() is not None


def prd_upstream_available() -> bool:
    """True when the prd-spec-generator (``prd-gen``) MCP server is configured."""
    return _server_command_runnable("prd-gen")
