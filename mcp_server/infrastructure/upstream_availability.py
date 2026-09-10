"""Detect whether upstream MCP integrations are reachable.

source: ADR-0620"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from mcp_server.infrastructure.config import MCP_CONNECTIONS_PATH
from mcp_server.infrastructure.file_io import read_json


def _server_command_runnable(server_name: str) -> bool:
    """True when mcp-connections.json wires ``server_name`` to a runnable command.

    source: ADR-0620"""
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
    """True when the ai-architect-mcp-codebase (``codebase``) MCP server is
    reachable.

    source: ADR-0620"""
    if _server_command_runnable("codebase"):
        return True
    # source: ADR-0620
    from mcp_server.infrastructure.pipeline_discovery import (  # noqa: PLC0415 — documented deferral: pipeline_discovery is heavier than this module; the gate stays cheap when already wired
        discover_pipeline_command,
    )

    return discover_pipeline_command() is not None


def prd_upstream_available() -> bool:
    """True when the prd-spec-generator (``prd-gen``) MCP server is configured."""
    return _server_command_runnable("prd-gen")
