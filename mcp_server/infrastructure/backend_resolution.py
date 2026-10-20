"""The one storage-backend resolution for the launcher, the hooks and the server.

Before ADR-1110 three entry points resolved the backend three ways: the
Claude Code launcher defaulted to SQLite (ADR-1104), while the wheel's hook
entry (``hypermnesia-mcp-hook``) and the server module (``python -m
mcp_server``) left a HOME with no marker and no URL to the engine's ``auto``
mode, which dials ``127.0.0.1:5432`` (measured 2026-10-20 on main df3a447: one
connection each from a fresh HOME; ``remember`` then failed with "Cortex
requires PostgreSQL in CLI mode"; issues #703, #704).

``settle_backend`` is now the only entry: an explicit setting wins, then the
marker; a HOME nothing decides gets its marker once (below), and the result
is always an explicit ``sqlite`` or ``postgresql`` — never ``auto``.

First-launch decision, once, when neither the environment nor a marker
decides:

- a methodology directory with nothing of Cortex in it is a fresh install:
  the SQLite store, without dialing anything;
- earlier Cortex state means a pre-ADR-1104 launch ran on this HOME. libpq
  then decided, with paths no probe can replay (TLS retry, GSS, services,
  password files, psycopg's connect timeout). So the decision only runs one
  way: SQLite only when that URL certainly failed, i.e. ``localhost`` has no
  address or every one of its addresses refuses 5432 and no ``PG*`` variable
  configures libpq otherwise. Anything else keeps PostgreSQL.

source: ADR-1104
source: ADR-1110
source: ADR-0740
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from typing import MutableMapping

from mcp_server.infrastructure import backend_marker
from mcp_server.infrastructure.backend_marker import (
    apply_backend_resolution,
    environment_decides,
    read_backend_marker,
    write_backend_marker,
)

LEGACY_HOST = "localhost"  # source: pre-ADR-1104 scripts/launcher.py default URL
LEGACY_PORT = 5432  # source: pre-ADR-1104 scripts/launcher.py default URL
LEGACY_URL = f"postgresql://{LEGACY_HOST}:{LEGACY_PORT}/cortex"  # source: ADR-1104
# source: ADR-1104 (bounds the TCP connect; a slower answer keeps PostgreSQL)
CONNECT_SECONDS = 3.0
# source: PostgreSQL docs, libpq-envars (every libpq setting is a PG* variable)
_LIBPQ_PREFIX = "PG"
_WRITTEN_BY = "first launch (ADR-1104, ADR-1110)"  # source: ADR-1110
_REFUSED = "refused"  # sentinel: this address actively refused


def has_earlier_state(methodology_dir: Path, marker_name: str) -> bool:
    """Whether Cortex wrote anything there: not the marker, its temp file, or
    a hidden file such as Finder's ``.DS_Store``."""
    if not methodology_dir.is_dir():
        return False
    return any(
        not entry.name.startswith((marker_name, "."))
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


def persist_first_decision(marker_path: Path | None = None) -> None:
    """Write the marker when the environment and no marker decide. Loud."""
    marker_path = marker_path or backend_marker.BACKEND_MARKER_PATH
    backend, why = decide(marker_path.parent, marker_path.name)
    path = write_backend_marker(backend, _WRITTEN_BY, marker_path)
    print(f"[cortex] storage: {backend} ({why}); recorded in {path}", file=sys.stderr)


def settle_backend(
    environ: MutableMapping[str, str], marker_path: Path | None = None
) -> str:
    """Resolve the backend for this process; return ``sqlite`` or ``postgresql``.

    Pre:  ``environ`` is mutable (normally ``os.environ``).
    Post: ``CORTEX_MEMORY_STORE_BACKEND`` is ``sqlite`` or ``postgresql``
          unless the operator set it explicitly; ``DATABASE_URL`` is set
          only for PostgreSQL. Raises ``BackendMarkerError`` on an
          unreadable marker (never guess a backend).

    source: ADR-1110
    """
    if not environment_decides(environ) and read_backend_marker(marker_path) is None:
        persist_first_decision(marker_path)
    apply_backend_resolution(environ, marker_path, default="sqlite")
    backend = environ.get("CORTEX_MEMORY_STORE_BACKEND", "")
    named_url = environ.get("CORTEX_MEMORY_DATABASE_URL", "").strip()
    if backend != "sqlite" and "DATABASE_URL" not in environ:
        if named_url:
            environ["DATABASE_URL"] = named_url
        elif backend == "postgresql":
            # source: ADR-1104 — the legacy local URL, only when PostgreSQL was chosen
            environ["DATABASE_URL"] = LEGACY_URL
    return backend
