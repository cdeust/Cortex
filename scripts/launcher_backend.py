"""Launcher host-option mapping and shared backend resolution.

source: ADR-1104
source: issues #703/#704
"""

from __future__ import annotations

import os
import sys


def map_database_option(environ) -> None:
    """``CLAUDE_PLUGIN_OPTION_DATABASE_URL`` (how hooks, Setup included, receive
    the user's ``database_url``) onto an empty ``DATABASE_URL`` (how the MCP
    server receives it): one setting, one meaning. source: ADR-1104"""
    option = environ.get("CLAUDE_PLUGIN_OPTION_DATABASE_URL", "").strip()
    if option and not environ.get("DATABASE_URL", "").strip():
        environ["DATABASE_URL"] = option


def apply() -> None:
    """One storage backend for the server and every hook.

    The host passes the user's ``database_url`` to the MCP server as
    ``DATABASE_URL`` and to hooks only as ``CLAUDE_PLUGIN_OPTION_DATABASE_URL``;
    both mean the same setting, mapped before anything else, so a configured
    database always wins over the managed server (ADR-1114). Then a
    ``managed`` marker attaches this launch to the plugin's own server;
    otherwise the shared precedence (backend_marker) with the plugin's
    default. A HOME nothing decides gets its marker once (launcher_backend):
    SQLite when fresh, the earlier local PostgreSQL when it still answers.
    PostgreSQL's local URL default applies only when a marker chose it.

    source: ADR-0505
    source: ADR-1104
    source: ADR-1114
    """
    map_database_option(os.environ)
    from mcp_server.infrastructure.backend_marker import (  # noqa: PLC0415 — resolvable once plugin_root is on sys.path
        BackendMarkerError,
    )
    from mcp_server.infrastructure.managed_pg import ManagedPgError  # noqa: PLC0415 — same path as above
    from mcp_server.infrastructure.backend_resolution import settle_backend  # noqa: PLC0415 — launcher adds plugin_root before apply, after importing this script

    try:
        settle_backend(os.environ)
    except (BackendMarkerError, ManagedPgError, OSError) as exc:
        print(f"[cortex-launcher] Cortex not ready: {exc}", file=sys.stderr)
        sys.exit(1)
