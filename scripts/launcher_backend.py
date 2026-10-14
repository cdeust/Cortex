"""First-launch backend decision for a HOME the precedence leaves open.

Before ADR-1104 a marketplace install never ran ``install-plugin.sh``, so it
had no marker, and the launcher sent it to ``postgresql://localhost:5432/cortex``.
A user whose memories live there must keep them: the README promises that an
existing PostgreSQL install is never silently downgraded. So, once, when
neither the environment nor a marker decides:

- a methodology directory with nothing of Cortex in it is a fresh install:
  the SQLite store, without dialing anything;
- earlier Cortex state there means a pre-ADR-1104 launch ran on this HOME: the
  ``install-plugin.sh`` detection (ADR-0740) decides, i.e. whether the local
  ``cortex`` database answers the way that URL connected (no password).

The decision is written as the marker and printed, so it is made once, the
same for the server and every hook, and never silently.

source: ADR-1104
source: ADR-0740
"""

from __future__ import annotations

import getpass
import socket
import struct
import sys
from pathlib import Path

LEGACY_HOST = "localhost"  # source: pre-ADR-1104 scripts/launcher.py default URL
LEGACY_PORT = 5432  # source: pre-ADR-1104 scripts/launcher.py default URL
LEGACY_DATABASE = "cortex"  # source: pre-ADR-1104 scripts/launcher.py default URL
# source: ADR-1104 (bounds a localhost handshake; libpq sets no connect timeout)
PROBE_SECONDS = 3.0
# source: PostgreSQL docs, protocol-message-formats, StartupMessage (3.0)
_PROTOCOL_3_0 = 196608
_AUTH_OK = 0  # source: PostgreSQL docs, protocol-message-formats, AuthenticationOk
_TERMINATE = b"X\x00\x00\x00\x04"  # source: PostgreSQL docs, protocol-message-formats
_WRITTEN_BY = "launcher (first launch, ADR-1104)"  # source: ADR-1104


def has_earlier_state(methodology_dir: Path, marker_name: str) -> bool:
    """Whether anything but the marker (or its temp file) is in the directory."""
    if not methodology_dir.is_dir():
        return False
    return any(
        not entry.name.startswith(marker_name) for entry in methodology_dir.iterdir()
    )


def _startup_message(user: str) -> bytes:
    params = b"user\x00" + user.encode() + b"\x00database\x00"
    body = (
        struct.pack("!i", _PROTOCOL_3_0)
        + params
        + LEGACY_DATABASE.encode()
        + b"\x00\x00"
    )
    return struct.pack("!i", len(body) + 4) + body


def _read_exactly(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("the server closed the connection")
        data += chunk
    return data


def _session_opens(sock: socket.socket) -> str:
    """'' once the server is ready for queries, else why it is not."""
    while True:
        kind, length = struct.unpack("!ci", _read_exactly(sock, 5))
        payload = _read_exactly(sock, length - 4)
        if kind == b"Z":
            return ""
        if kind == b"E":
            fields = [f for f in payload.split(b"\x00") if f[:1] == b"M"]
            return fields[0][1:].decode(errors="replace") if fields else "error"
        if kind == b"R" and struct.unpack("!i", payload[:4])[0] != _AUTH_OK:
            return "the server asks for a password"


def local_database_answer(user: str) -> str:
    """'' when the local ``cortex`` database opens a session, else the reason."""
    try:
        with socket.create_connection(
            (LEGACY_HOST, LEGACY_PORT), timeout=PROBE_SECONDS
        ) as sock:
            sock.sendall(_startup_message(user))
            reason = _session_opens(sock)
            if not reason:
                sock.sendall(_TERMINATE)
            return reason
    except OSError as exc:
        return str(exc) or type(exc).__name__


def decide(methodology_dir: Path, marker_name: str) -> tuple[str, str]:
    """(backend, why) for a HOME with no marker and no explicit setting."""
    if not has_earlier_state(methodology_dir, marker_name):
        return "sqlite", "fresh install"
    target = f"{LEGACY_HOST}:{LEGACY_PORT}/{LEGACY_DATABASE}"
    reason = local_database_answer(getpass.getuser())
    if not reason:
        return (
            "postgresql",
            f"earlier Cortex state and the database at {target} answers",
        )
    return "sqlite", (
        f"earlier Cortex state, but no database answered at {target} ({reason});"
        " set database_url to use PostgreSQL"
    )


def persist_first_decision() -> None:
    """Write the marker when the environment and no marker decide. Loud."""
    from mcp_server.infrastructure.backend_marker import (  # noqa: PLC0415 — resolvable once plugin_root is on sys.path
        BACKEND_MARKER_PATH,
        write_backend_marker,
    )

    backend, why = decide(BACKEND_MARKER_PATH.parent, BACKEND_MARKER_PATH.name)
    path = write_backend_marker(backend, _WRITTEN_BY, BACKEND_MARKER_PATH)
    print(
        f"[cortex-launcher] storage: {backend} ({why}); recorded in {path}",
        file=sys.stderr,
    )
