"""source: ADR-0508"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable
from pathlib import Path

from mcp_server.infrastructure import capture_socket as endpoint
from mcp_server.infrastructure.capture_transport import Limits, encode, remaining, send

Spawn = Callable[[socket.socket, int], None]


def _connect_or_spawn(runtime: Path, deadline: float, spawn: Spawn) -> socket.socket:
    path = runtime / "socket"
    # source: ADR-0508
    with endpoint.lease(runtime / "launch.lock", deadline):
        try:
            return endpoint.connect(path, remaining(deadline))
        except (FileNotFoundError, ConnectionRefusedError):
            # source: ADR-0508
            _start_worker(runtime, deadline, spawn)
        return endpoint.connect(path, remaining(deadline))


def _start_worker(runtime: Path, deadline: float, spawn: Spawn) -> None:
    path = runtime / "socket"
    # source: ADR-0508
    with endpoint.lease(runtime / "worker.lock", deadline) as descriptor:
        endpoint.remove_socket(path)
        with endpoint.listen(path) as listener:
            spawn(listener, descriptor)


def deliver(
    root: Path, payload: dict[str, object], limits: Limits, spawn: Spawn
) -> None:
    """Return after admission; uncertain delivery raises and is never replayed.

    source: ADR-0508"""
    frame = encode(payload, limits.max_bytes)
    deadline = time.monotonic() + limits.timeout
    runtime = endpoint.runtime_directory(root)
    with _connect_or_spawn(runtime, deadline, spawn) as connection:
        send(connection, frame, deadline)
