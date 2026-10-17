"""First-launch backend decision for a HOME the precedence leaves open.

Before ADR-1104 a marketplace install never ran ``install-plugin.sh``, so it
had no marker, and the launcher sent it to ``postgresql://localhost:5432/cortex``
through libpq. A user whose memories live there must keep them: the README
promises that an existing PostgreSQL install is never silently downgraded.
So, once, when neither the environment nor a marker decides:

- a methodology directory with nothing of Cortex in it is a fresh install:
  the SQLite store, without dialing anything;
- earlier Cortex state means a pre-ADR-1104 launch ran on this HOME. libpq
  then decided, with paths no probe can replay (TLS retry, GSS, services,
  password files, psycopg's connect timeout). So the decision only runs one
  way: SQLite only when that URL certainly failed, i.e. ``localhost`` has no
  address or every one of its addresses refuses 5432 and no ``PG*`` variable
  configures libpq otherwise. Anything else keeps PostgreSQL, where libpq
  connects or fails loudly with the real error, as before this decision (the
  SessionStart hook still creates a missing ``cortex`` database, setup_db).

The decision is written as the marker and printed, so it is made once, the
same for the server and every hook, and never silently.

source: ADR-1104
source: ADR-0740
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

LEGACY_HOST = "localhost"  # source: pre-ADR-1104 scripts/launcher.py default URL
LEGACY_PORT = 5432  # source: pre-ADR-1104 scripts/launcher.py default URL
# source: ADR-1104 (bounds the TCP connect; a slower answer keeps PostgreSQL)
CONNECT_SECONDS = 3.0
# source: PostgreSQL docs, libpq-envars (every libpq setting is a PG* variable)
_LIBPQ_PREFIX = "PG"
WRITTEN_BY = "launcher (first launch, ADR-1104)"  # source: ADR-1104
_REFUSED = "refused"  # sentinel: this address actively refused


def has_earlier_state(methodology_dir: Path, marker_name: str) -> bool:
    """Whether Cortex wrote anything there: not the marker, its temp file, a
    hidden file such as Finder's ``.DS_Store``, or the managed server's root
    (Setup creates it before it may select the store, ADR-1110)."""
    from mcp_server.infrastructure.managed_pg import ROOT_NAME  # noqa: PLC0415 — resolvable once plugin_root is on sys.path

    if not methodology_dir.is_dir():
        return False
    return any(
        not entry.name.startswith((marker_name, ".")) and entry.name != ROOT_NAME
        for entry in methodology_dir.iterdir()
    )


def legacy_store_answer(environ: dict) -> tuple[bool, str]:
    """(the old URL certainly failed, why)."""
    configured = sorted(name for name in environ if name.startswith(_LIBPQ_PREFIX))
    if configured:
        return False, f"libpq is configured ({', '.join(configured)}); libpq decides"
    try:
        addresses = socket.getaddrinfo(
            LEGACY_HOST, LEGACY_PORT, type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        return True, f"{LEGACY_HOST} has no address ({exc})"
    unclear = [_connect_error(address) for address in addresses]
    unclear = [error for error in unclear if error is not _REFUSED]
    if not unclear:
        return True, "every address refuses the connection; nothing listens there"
    if None in unclear:
        return False, "a server listens there; libpq decides"
    return False, f"no clear answer ({unclear[0]}); libpq decides"


def _connect_error(address: tuple):
    """None when it connects, ``_REFUSED`` when refused, else the error. Each
    address is tried as libpq tries them (AF_UNSPEC, every result)."""
    family, kind, proto, _name, sockaddr = address
    try:
        with socket.socket(family, kind, proto) as sock:
            sock.settimeout(CONNECT_SECONDS)
            sock.connect(sockaddr)
    except ConnectionRefusedError:
        return _REFUSED
    except OSError as exc:
        return exc or type(exc).__name__
    return None


def decide(methodology_dir: Path, marker_name: str) -> tuple[str, str]:
    """(backend, why) for a HOME with no marker and no explicit setting."""
    if not has_earlier_state(methodology_dir, marker_name):
        return "sqlite", "fresh install"
    target = f"{LEGACY_HOST}:{LEGACY_PORT}"
    failed, why = legacy_store_answer(dict(os.environ))
    if not failed:
        return "postgresql", f"earlier Cortex state; {target}: {why}"
    return "sqlite", (
        f"earlier Cortex state, but {target}: {why}; set database_url to use PostgreSQL"
    )


def persist_first_decision() -> None:
    """Write the marker when the environment and no marker decide. Loud."""
    from mcp_server.infrastructure.backend_marker import (  # noqa: PLC0415 — resolvable once plugin_root is on sys.path
        BACKEND_MARKER_PATH,
        write_backend_marker,
    )

    backend, why = decide(BACKEND_MARKER_PATH.parent, BACKEND_MARKER_PATH.name)
    path = write_backend_marker(backend, WRITTEN_BY, BACKEND_MARKER_PATH)
    print(
        f"[cortex-launcher] storage: {backend} ({why}); recorded in {path}",
        file=sys.stderr,
    )


def map_database_option(environ) -> None:
    """``CLAUDE_PLUGIN_OPTION_DATABASE_URL`` (how hooks, Setup included, receive
    the user's ``database_url``) onto an empty ``DATABASE_URL`` (how the MCP
    server receives it): one setting, one meaning. source: ADR-1104"""
    option = environ.get("CLAUDE_PLUGIN_OPTION_DATABASE_URL", "").strip()
    if option and not environ.get("DATABASE_URL", "").strip():
        environ["DATABASE_URL"] = option


def _resolve() -> None:
    """ADR-1104's chain; a ``managed`` marker attaches to that server."""
    from mcp_server.infrastructure.backend_marker import (  # noqa: PLC0415 — resolvable once plugin_root is on sys.path
        apply_backend_resolution,
        environment_decides,
        read_backend_marker,
    )

    if not environment_decides(os.environ) and read_backend_marker() is None:
        persist_first_decision()
    apply_backend_resolution(os.environ, default="sqlite")


def apply() -> None:
    """One storage backend for the server and every hook.

    The host passes the user's ``database_url`` to the MCP server as
    ``DATABASE_URL`` and to hooks only as ``CLAUDE_PLUGIN_OPTION_DATABASE_URL``;
    both mean the same setting, mapped before anything else, so a configured
    database always wins over the managed server (ADR-1110). Then a
    ``managed`` marker attaches this launch to the plugin's own server;
    otherwise the shared precedence (backend_marker) with the plugin's
    default. A HOME nothing decides gets its marker once (launcher_backend):
    SQLite when fresh, the earlier local PostgreSQL when it still answers.
    PostgreSQL's local URL default applies only when a marker chose it.

    source: ADR-0505
    source: ADR-1104
    source: ADR-1110
    """
    map_database_option(os.environ)
    from mcp_server.infrastructure.backend_marker import (  # noqa: PLC0415 — resolvable once plugin_root is on sys.path
        BackendMarkerError,
    )
    from mcp_server.infrastructure.managed_pg import ManagedPgError  # noqa: PLC0415 — same path as above

    try:
        _resolve()
    except (BackendMarkerError, ManagedPgError, OSError) as exc:
        print(f"[cortex-launcher] Cortex not ready: {exc}", file=sys.stderr)
        sys.exit(1)
    if (
        "DATABASE_URL" not in os.environ
        and os.environ.get("CORTEX_MEMORY_STORE_BACKEND", "") == "postgresql"
    ):
        os.environ["DATABASE_URL"] = "postgresql://localhost:5432/cortex"
