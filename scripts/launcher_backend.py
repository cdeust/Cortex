"""The Claude Code launcher's storage-backend step.

The host passes the user's ``database_url`` to the MCP server as
``DATABASE_URL`` and to hooks only as ``CLAUDE_PLUGIN_OPTION_DATABASE_URL``;
both mean the same setting. The resolution itself is the one shared with the
hooks and the server (``mcp_server.infrastructure.backend_resolution``).

source: ADR-1104
source: ADR-1110
"""

from __future__ import annotations

import os
import sys


def apply() -> None:
    """One storage backend for the server and every hook; exit 1 when unsure."""
    option = os.environ.get("CLAUDE_PLUGIN_OPTION_DATABASE_URL", "").strip()
    if option and not os.environ.get("DATABASE_URL", "").strip():
        os.environ["DATABASE_URL"] = option
    from mcp_server.infrastructure.backend_marker import BackendMarkerError  # noqa: PLC0415 — resolvable once plugin_root is on sys.path
    from mcp_server.infrastructure.backend_resolution import settle_backend  # noqa: PLC0415 — resolvable once plugin_root is on sys.path

    try:
        settle_backend(os.environ)
    except (BackendMarkerError, OSError) as exc:
        print(f"[cortex-launcher] Cortex not ready: {exc}", file=sys.stderr)
        sys.exit(1)
