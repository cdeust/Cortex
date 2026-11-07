"""`cortex doctor` check: the plugin's managed PostgreSQL server (ADR-1114, B3).

With a ``managed`` backend marker the doctor is a direct launch like any other
(owner decision D1): it attaches to the server, starting it when nobody runs
it, exactly as the MCP server and the hooks do, so the PostgreSQL checks that
follow run against the store memories actually live in. A server that cannot
run is a failed check naming its cause, never a traceback (round-3 review B3:
the doctor crashed on every fresh managed install).

source: ADR-1114
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, MutableMapping

from mcp_server.infrastructure import managed_pg
from mcp_server.infrastructure.backend_marker import (
    MANAGED,
    apply_backend_resolution,
    environment_decides,
    read_backend_marker,
)

NAME = "Managed PostgreSQL server"  # source: ADR-1114 (the server's name in docs)
_FIX = (
    "Run `claude --init-only` (Setup installs the server again; your memories "
    "under ~/.claude/methodology/managed-pg are kept), or set database_url to "
    "use your own PostgreSQL"
)


def selected(environ: MutableMapping[str, str]) -> bool:
    """Whether this process's store is the managed server (nothing started)."""
    if managed_pg.serves(environ) is not None:
        return True
    if environment_decides(environ):
        return False
    marker = read_backend_marker()
    return marker is not None and marker["backend"] == MANAGED


def managed_server(check: Callable[..., Any]) -> Any:
    """Attach to the managed server and report where it runs.

    Pre-condition: ``check`` is doctor's ``Check`` constructor; ``selected``.
    Post-condition: ``DATABASE_URL`` names the server when it runs; any
    failure is a failed check carrying the supervisor's cause."""
    try:
        apply_backend_resolution(os.environ)
    except (managed_pg.ManagedPgError, OSError) as exc:
        return check(NAME, False, str(exc), _FIX)
    root = os.environ.get(managed_pg.ROOT_ENV, "")
    port = managed_pg.read_json(managed_pg.PgPaths(Path(root)).status).get("port")
    return check(NAME, True, f"running on {managed_pg.HOST}:{port}, cluster {root}")
