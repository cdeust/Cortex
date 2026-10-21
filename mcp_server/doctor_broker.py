"""Doctor's view of the store broker (ADR-1112 increment 5).

Asks the broker of the configured store, without starting one, whether it
runs, which schema version it serves and its PID. "Not running" is not a
failure: the first client starts it. A broker that answers with a refusal
(a schema this code cannot use) is.

source: ADR-1112 decisions 1, 6 and 7
"""

from __future__ import annotations

import os
import sys
from typing import Any

from mcp_server.shared.redaction import scrub_secrets


def _probe(url: str) -> dict[str, Any]:
    from mcp_server.infrastructure import capture_socket  # noqa: PLC0415 — Unix transport only
    from mcp_server.infrastructure.broker_client import BrokerClient  # noqa: PLC0415
    from mcp_server.infrastructure.broker_endpoint import store_key  # noqa: PLC0415
    from mcp_server.infrastructure.broker_unix import (  # noqa: PLC0415
        SOCKET_NAME,
        SocketChannel,
        runtime_directory,
        socket_root,
    )
    from mcp_server.infrastructure.config import CLAUDE_DIR  # noqa: PLC0415

    key = store_key(url, CLAUDE_DIR)
    path = runtime_directory(socket_root(CLAUDE_DIR, key), key) / SOCKET_NAME
    if not path.exists():
        return {"running": False, "socket": str(path)}
    client = BrokerClient(
        lambda deadline: SocketChannel(capture_socket.connect(path, 2.0)), "doctor"
    )
    try:
        client.connect()
    except ConnectionError:
        return {"running": False, "socket": str(path)}
    try:
        return {"running": True, "socket": str(path), "pid": client.broker_pid()}
    finally:
        client.close()


def store_broker_check() -> dict[str, Any]:
    """Fields of doctor's ``McpCheck`` for the store broker."""
    name = "store broker"
    url = os.environ.get("DATABASE_URL", "")
    if not url or sys.platform == "win32":
        reason = "no DATABASE_URL" if not url else "named pipe: not probed by doctor"
        return {
            "name": name,
            "ok": True,
            "detail": f"skipped ({reason})",
            "severity": "warn",
        }
    try:
        status = _probe(url)
    except Exception as exc:  # noqa: BLE001 — every failure is reported verbatim
        return {
            "name": name,
            "ok": False,
            "detail": "the broker refused or could not be probed",
            "error": scrub_secrets(f"{type(exc).__name__}: {exc}"),
            "fix": "Read the broker's log next to its socket (broker.log, broker.out).",
        }
    if not status["running"]:
        detail = f"not running; the first client starts it ({status['socket']})"
        return {"name": name, "ok": True, "detail": detail, "severity": "ok"}
    detail = f"running, pid {status['pid']} ({status['socket']})"
    return {"name": name, "ok": True, "detail": detail, "severity": "ok"}


def database_roles_check() -> dict[str, Any]:
    """Whether migration and runtime run as two roles (ADR-1112 least
    privilege). One role for both is reported, not refused."""
    name = "database roles"
    url = os.environ.get("DATABASE_URL", "")
    migration = os.environ.get("CORTEX_MIGRATION_DATABASE_URL", "")
    if not url:
        return {
            "name": name,
            "ok": True,
            "detail": "skipped (no DATABASE_URL)",
            "severity": "warn",
        }
    from mcp_server.infrastructure.pg_roles import role_of  # noqa: PLC0415 — PG-only

    runtime = role_of(url)
    if not migration or role_of(migration) == runtime:
        return {
            "name": name,
            "ok": True,
            "detail": f"one role ({runtime}) migrates and serves: no separation",
            "fix": "Run scripts/setup_least_privilege.py as an administrator, then set "
            "CORTEX_MIGRATION_DATABASE_URL to the migration role and DATABASE_URL "
            "to the runtime role.",
            "severity": "warn",
        }
    detail = f"migration {role_of(migration)}, runtime {runtime}"
    return {"name": name, "ok": True, "detail": detail, "severity": "ok"}
