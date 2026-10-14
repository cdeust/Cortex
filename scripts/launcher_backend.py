"""First-launch backend decision for a HOME the precedence leaves open.

Before ADR-1104 a marketplace install never ran ``install-plugin.sh``, so it
had no marker, and the launcher sent it to ``postgresql://localhost:5432/cortex``.
A user whose memories live there must keep them: the README promises that an
existing PostgreSQL install is never silently downgraded. So, once, when
neither the environment nor a marker decides:

- a methodology directory with nothing of Cortex in it is a fresh install:
  the SQLite store, without dialing anything;
- earlier Cortex state there means a pre-ADR-1104 launch ran on this HOME:
  ``install-plugin.sh`` (ADR-0740) kept PostgreSQL when the local ``cortex``
  database was there. Main reached it through libpq, which retries without
  TLS, honours PGSSLMODE, client certificates and Kerberos: a probe cannot
  replay all of it. So the error only runs one way. SQLite is chosen only when
  main certainly failed: nothing answers on the port (or within the bound;
  libpq would have waited forever), the server says the
  ``cortex`` database does not exist, or it asks a plaintext client for a
  password libpq would not have (PGPASSWORD, password file; launcher_pgpass).
  Any other answer keeps PostgreSQL, where libpq connects or fails loudly
  with the real error, as on main.

The decision is written as the marker and printed, so it is made once, the
same for the server and every hook, and never silently.

source: ADR-1104
source: ADR-0740
"""

from __future__ import annotations

import os
import socket
import struct
import sys
import time
from pathlib import Path

import launcher_pgpass

LEGACY_HOST = "localhost"  # source: pre-ADR-1104 scripts/launcher.py default URL
LEGACY_PORT = 5432  # source: pre-ADR-1104 scripts/launcher.py default URL
LEGACY_DATABASE = "cortex"  # source: pre-ADR-1104 scripts/launcher.py default URL
# source: ADR-1104 (bounds the whole localhost probe; libpq sets no connect timeout)
PROBE_SECONDS = 3.0
# source: PostgreSQL docs, protocol-message-formats, StartupMessage (3.0)
_PROTOCOL_3_0 = 196608
# source: PostgreSQL docs, protocol-message-formats, SSLRequest
_SSL_REQUEST = struct.pack("!ii", 8, 80877103)
# source: PostgreSQL docs, protocol-message-formats (the Int32 length counts itself)
_LENGTH_FIELD = 4
_AUTH_OK = 0  # source: PostgreSQL docs, protocol-message-formats, AuthenticationOk
# source: PostgreSQL docs, protocol-message-formats: CleartextPassword (3),
# MD5Password (5), SASL (10) are the requests a password answers
_SECRET_REQUESTS = frozenset({3, 5, 10})
# source: PostgreSQL docs, errcodes-appendix (invalid_catalog_name)
_NO_DATABASE = "3D000"
_TERMINATE = b"X\x00\x00\x00\x04"  # source: PostgreSQL docs, protocol-message-formats
_WRITTEN_BY = "launcher (first launch, ADR-1104)"  # source: ADR-1104


def has_earlier_state(methodology_dir: Path, marker_name: str) -> bool:
    """Whether Cortex wrote anything there: not the marker, its temp file, or
    a hidden file such as Finder's ``.DS_Store``."""
    if not methodology_dir.is_dir():
        return False
    return any(
        not entry.name.startswith((marker_name, "."))
        for entry in methodology_dir.iterdir()
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


class _Deadline:
    """One bound for the whole probe, applied before every socket call."""

    def __init__(self, seconds: float) -> None:
        self._end = time.monotonic() + seconds

    def arm(self, sock: socket.socket) -> None:
        left = self._end - time.monotonic()
        if left <= 0:
            raise TimeoutError(f"no answer within {PROBE_SECONDS:g} s")
        sock.settimeout(left)


def _read_exactly(sock: socket.socket, size: int, deadline: _Deadline) -> bytes:
    data = b""
    while len(data) < size:
        deadline.arm(sock)
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("the server closed the connection")
        data += chunk
    return data


def _messages(sock: socket.socket, deadline: _Deadline):
    while True:
        kind, length = struct.unpack("!ci", _read_exactly(sock, 5, deadline))
        if length < _LENGTH_FIELD:
            raise ValueError(f"malformed server message (length {length})")
        yield kind, _read_exactly(sock, length - _LENGTH_FIELD, deadline)


def _error_fields(payload: bytes) -> dict:
    return {f[:1]: f[1:].decode(errors="replace") for f in payload.split(b"\x00") if f}


def _verdict(kind: bytes, payload: bytes, environ: dict, user: str):
    """(main certainly failed, why) for one server message, or None to read on."""
    if kind == b"Z":
        return False, "the database answers"
    if kind == b"E":
        fields = _error_fields(payload)
        message = fields.get(b"M", "error")
        return fields.get(b"C") == _NO_DATABASE, f"the server answered: {message}"
    if kind != b"R":
        return None
    code = struct.unpack("!i", payload[:4])[0]
    if code == _AUTH_OK:
        return None
    if code not in _SECRET_REQUESTS:
        return False, f"the server asks for authentication libpq handles (code {code})"
    if launcher_pgpass.has_credentials(
        environ, LEGACY_HOST, LEGACY_PORT, LEGACY_DATABASE, user
    ):
        return False, "the server asks for a password libpq has"
    return True, "the server asks for a password and none is set (PGPASSWORD, pgpass)"


def _conversation(sock, deadline: _Deadline, environ: dict, user: str):
    deadline.arm(sock)
    sock.sendall(_SSL_REQUEST)
    if _read_exactly(sock, 1, deadline) != b"N":
        return False, "the server answers the TLS request; libpq decides"
    deadline.arm(sock)
    sock.sendall(_startup_message(user))
    for kind, payload in _messages(sock, deadline):
        verdict = _verdict(kind, payload, environ, user)
        if verdict is not None:
            if kind == b"Z":
                sock.sendall(_TERMINATE)
            return verdict
    raise ConnectionError("the server stopped answering")  # _messages never ends


def legacy_store_answer(environ: dict) -> tuple:
    """(main certainly failed, why) for the old local URL."""
    try:
        user = launcher_pgpass.login_user(environ)
    except LookupError as exc:
        return True, str(exc)
    try:
        sock = socket.create_connection(
            (LEGACY_HOST, LEGACY_PORT), timeout=PROBE_SECONDS
        )
    except OSError as exc:
        return True, f"nothing answered ({exc})"
    with sock:
        try:
            return _conversation(sock, _Deadline(PROBE_SECONDS), environ, user)
        except (TimeoutError, socket.timeout) as exc:
            # libpq sets no timeout: main would have hung on this listener.
            return True, f"no answer ({exc or 'timed out'})"
        except (OSError, struct.error, ValueError) as exc:
            return False, f"unclear answer ({exc or type(exc).__name__}); libpq decides"


def decide(methodology_dir: Path, marker_name: str) -> tuple[str, str]:
    """(backend, why) for a HOME with no marker and no explicit setting."""
    if not has_earlier_state(methodology_dir, marker_name):
        return "sqlite", "fresh install"
    target = f"{LEGACY_HOST}:{LEGACY_PORT}/{LEGACY_DATABASE}"
    failed, why = legacy_store_answer(dict(os.environ))
    if not failed:
        return "postgresql", f"earlier Cortex state; {target}: {why}"
    return "sqlite", (
        f"earlier Cortex state, but the old store at {target} cannot open ({why});"
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
