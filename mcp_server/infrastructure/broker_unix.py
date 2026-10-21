"""The broker's Unix transport: private socket, kernel lease, framed channel.

Everything that makes the capture worker's socket safe is reused as is
(``capture_socket``, ``capture_peer``, ADR-0510/0512): a 0700 directory owned
by the user, a 0600 socket whose owner and mode are checked before every
connect, the kernel peer UID checked by both sides, a lifetime ``flock``
lease held by the broker and inherited at spawn, and a launch lock so that
concurrent clients start one broker. Only the directory name differs
(``.store-broker``).

source: ADR-1112 (transport); ADR-0512, ADR-0510, ADR-0508 (the pattern)
"""

from __future__ import annotations

import os
import socket
import sys
from collections.abc import Callable
from pathlib import Path

from mcp_server.infrastructure import capture_socket as endpoint
from mcp_server.infrastructure.capture_peer import authenticate
from mcp_server.infrastructure.broker_protocol import (
    HEADER_SIZE,
    ProtocolError,
    frame,
    frame_length,
    remaining,
)

# source: ADR-1112 the broker's private directory under the Cortex root
RUNTIME_NAME = ".store-broker"
SOCKET_NAME = "socket"
LEASE_NAME = "broker.lock"
LAUNCH_NAME = "launch.lock"

Spawn = Callable[[socket.socket, int], None]


class SocketChannel:
    """Framed messages over one accepted or connected Unix stream socket."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock

    def send_frame(self, data: bytes, limit: int, deadline: float | None) -> None:
        self.sock.settimeout(remaining(deadline))
        self.sock.sendall(frame(data, limit))

    def _read_exact(self, length: int, deadline: float | None) -> bytes:
        chunks = bytearray()
        while len(chunks) < length:
            self.sock.settimeout(remaining(deadline))
            chunk = self.sock.recv(min(length - len(chunks), 1 << 20))
            if not chunk:
                raise ConnectionError("broker channel closed")
            chunks.extend(chunk)
        return bytes(chunks)

    def recv_frame(self, limit: int, deadline: float | None) -> bytes:
        length = frame_length(self._read_exact(HEADER_SIZE, deadline), limit)
        return self._read_exact(length, deadline)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


# source: unix(4) on macOS (sun_path holds 104 bytes) and unix(7) on Linux
# (108); one byte for the terminating NUL
_SUN_PATH_MAX = 103


def socket_root(root: Path, key: str) -> Path:
    """Where the store's private directory lives: under the Cortex root when
    the socket path fits in ``sun_path``, else under the user's runtime
    directory (``$XDG_RUNTIME_DIR``, or ``/tmp/cortex-<uid>`` resolved), which
    ``runtime_directory`` creates owner-only and checks like the root."""
    candidate = root.expanduser().absolute() / RUNTIME_NAME / key / SOCKET_NAME
    if len(os.fsencode(str(candidate))) <= _SUN_PATH_MAX:
        return root
    base = os.environ.get("XDG_RUNTIME_DIR") or os.path.realpath("/tmp")
    return Path(base) / f"cortex-{os.geteuid()}"


def runtime_directory(root: Path, key: str) -> Path:
    """``root/.store-broker/<key>``: owner-only, one per store. ``root`` is
    created owner-only if missing (the ``socket_root`` under ``/tmp``); its
    owner and mode are then checked like every parent (ADR-0512)."""
    root.expanduser().absolute().mkdir(mode=endpoint.PRIVATE_DIR, exist_ok=True)
    return endpoint.runtime_directory(root / RUNTIME_NAME, key)


def accept(listener: socket.socket) -> SocketChannel:
    """Accept one client and check its kernel UID before reading anything."""
    conn, _ = listener.accept()
    try:
        authenticate(conn)
    except BaseException:
        conn.close()
        raise
    return SocketChannel(conn)


def peer_pid(channel: SocketChannel) -> int | None:
    """The client's PID where the kernel reports it (Linux), else None."""
    import struct  # noqa: PLC0415 — Linux-only detail

    if sys.platform != "linux":
        return None
    creds = struct.Struct("iII")
    raw = channel.sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, creds.size)
    return creds.unpack(raw)[0]


def peer_label(channel: SocketChannel) -> str:
    """The kernel identity logged with each connection (UID already checked
    equal to the broker's own; PID where the kernel reports it)."""
    pid = peer_pid(channel)
    return f"uid={os.geteuid()} pid={'?' if pid is None else pid}"


def _start(runtime: Path, deadline: float, spawn: Spawn) -> None:
    path = runtime / SOCKET_NAME
    # source: ADR-0508 (a live lease is never a reason to start a second one)
    with endpoint.lease(runtime / LEASE_NAME, deadline) as descriptor:
        endpoint.remove_socket(path)
        with endpoint.listen(path) as listener:
            spawn(listener, descriptor)


def connect_or_spawn(
    root: Path, key: str, deadline: float, spawn: Spawn
) -> SocketChannel:
    """Connect to the running broker, launching it once if none answers.

    Under the launch lock: a refused or absent socket means no broker; the
    caller takes the lease (it is free only if no broker lives), binds the
    socket and hands both to the spawned broker. A live lease with an
    unusable socket is an explicit failure, never a second broker."""
    runtime = runtime_directory(root, key)
    path = runtime / SOCKET_NAME
    with endpoint.lease(runtime / LAUNCH_NAME, deadline):
        try:
            return SocketChannel(endpoint.connect(path, _left(deadline)))
        except (FileNotFoundError, ConnectionRefusedError):
            _start(runtime, deadline, spawn)
        return SocketChannel(endpoint.connect(path, _left(deadline)))


def _left(deadline: float) -> float:
    left = remaining(deadline)
    if left is None:
        raise ProtocolError("a connect needs a deadline")
    return left
