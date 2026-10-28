"""Shared first-launch backend resolution for launcher, wheel hooks and server.

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
from typing import Mapping, MutableMapping

from mcp_server.infrastructure import backend_marker

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
    (Setup creates it before it may select the store, ADR-1114)."""
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


def decide(
    methodology_dir: Path, marker_name: str, environ: Mapping[str, str] | None = None
) -> tuple[str, str]:
    """(backend, why) for a HOME with no marker and no explicit setting."""
    if not has_earlier_state(methodology_dir, marker_name):
        return "sqlite", "fresh install"
    target = f"{LEGACY_HOST}:{LEGACY_PORT}"
    failed, why = legacy_store_answer(dict(os.environ if environ is None else environ))
    if not failed:
        return "postgresql", f"earlier Cortex state; {target}: {why}"
    return "sqlite", (
        f"earlier Cortex state, but {target}: {why}; set database_url to use PostgreSQL"
    )


def persist_first_decision(
    marker_path: Path | None = None, environ: Mapping[str, str] | None = None
) -> None:
    """Persist the first-launch choice; retain ADR-1104's marker identity.

    Setup recognizes WRITTEN_BY when deciding if an empty SQLite store may
    be provisioned as managed PostgreSQL (scripts/launcher_pg_select.py).
    """
    marker_path = marker_path or backend_marker.BACKEND_MARKER_PATH
    backend, why = decide(marker_path.parent, marker_path.name, environ)
    path = backend_marker.write_backend_marker(backend, WRITTEN_BY, marker_path)
    print(
        f"[cortex] storage: {backend} ({why}); recorded in {path}",
        file=sys.stderr,
    )


def settle_backend(
    environ: MutableMapping[str, str], marker_path: Path | None = None
) -> str:
    """Apply one first-launch policy before settings bind on every entry point.

    Explicit settings/URLs win; otherwise the saved marker wins, including
    managed PostgreSQL (ADR-1114). An undecided HOME persists ADR-1104's
    choice. URL-only and explicitly auto configurations remain engine-owned.
    Marker, filesystem and managed-server failures propagate to the caller.

    source: issues #703/#704; docs/verification/draft-relevance-20261027.md
    """
    if (
        not backend_marker.environment_decides(environ)
        and backend_marker.read_backend_marker(marker_path) is None
    ):
        persist_first_decision(marker_path, environ)
    backend_marker.apply_backend_resolution(environ, marker_path, default="sqlite")
    backend = environ.get("CORTEX_MEMORY_STORE_BACKEND", "")
    named_url = environ.get("CORTEX_MEMORY_DATABASE_URL", "").strip()
    if backend != "sqlite" and not environ.get("DATABASE_URL", "").strip():
        if named_url:
            environ["DATABASE_URL"] = named_url
        elif backend == "postgresql":
            # source: ADR-1104 -- only a selected PostgreSQL uses the legacy URL.
            environ["DATABASE_URL"] = "postgresql://localhost:5432/cortex"
    return backend


def resolve_auto_backend() -> None:
    """Export the process engine's auto choice for both hook dispatch adapters.

    Call after ``settle_backend`` and before raw-SQL hook imports.
    source: ADR-0535
    Native review: PR804 discussions4388465600 and4388819779.
    """
    if os.environ.get("CORTEX_MEMORY_STORE_BACKEND") != "auto":
        return
    if (
        os.environ.get("DATABASE_URL", "").strip()
        or os.environ.get("CORTEX_MEMORY_DATABASE_URL", "").strip()
    ):
        return
    from mcp_server.infrastructure.memory_store import get_shared_store  # noqa: PLC0415 — runtime selection follows first-launch environment resolution
    from mcp_server.infrastructure.memory_config import get_memory_settings  # noqa: PLC0415 — preserve the engine-selected PostgreSQL URL
    from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore  # noqa: PLC0415 — runtime selection follows first-launch environment resolution

    store = get_shared_store()
    if isinstance(store, SqliteMemoryStore):
        os.environ["CORTEX_MEMORY_STORE_BACKEND"] = "sqlite"
    else:
        os.environ["CORTEX_MEMORY_STORE_BACKEND"] = "postgresql"
        os.environ["DATABASE_URL"] = get_memory_settings().DATABASE_URL
