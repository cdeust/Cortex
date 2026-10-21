"""The broker's Unix endpoint (ADR-1112 decisions 2 and 7): per-store private
directory, foreign peers refused before any frame, a live lease without a
usable socket is an explicit failure and never a second broker.

source: ADR-1112
"""

from __future__ import annotations

import os
import socket
import stat
import sys
import tempfile
import time
from pathlib import Path

import pytest

from mcp_server.infrastructure import broker_unix
from mcp_server.infrastructure import capture_socket as endpoint

pytestmark = pytest.mark.skipif(
    sys.platform not in {"darwin", "linux"}, reason="Unix peer credentials"
)


@pytest.fixture
def root():
    # sockaddr_un holds about 104 bytes on macOS: a short root under /tmp
    with tempfile.TemporaryDirectory(prefix="bu-", dir=Path("/tmp").resolve()) as path:
        yield Path(path)


def test_each_store_gets_its_own_owner_only_directory(root):
    first = broker_unix.runtime_directory(root, "aaaa")
    second = broker_unix.runtime_directory(root, "bbbb")
    assert first != second and first.parent == second.parent == root / ".store-broker"
    for path in (first, second, root / ".store-broker"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o700


def test_a_foreign_peer_is_closed_before_any_frame(root, monkeypatch):
    path = broker_unix.runtime_directory(root, "k") / broker_unix.SOCKET_NAME
    listener = endpoint.listen(path)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(str(path))

        def foreign(connection):
            raise PermissionError("capture socket peer belongs to a different user")

        monkeypatch.setattr(broker_unix, "authenticate", foreign)
        with pytest.raises(PermissionError):
            broker_unix.accept(listener)
        client.settimeout(5)
        assert client.recv(1) == b""  # closed by the broker, nothing was read
    finally:
        client.close()
        listener.close()


def test_a_live_lease_without_a_socket_never_starts_a_second_broker(root):
    runtime = broker_unix.runtime_directory(root, "k")
    spawned: list[int] = []
    with endpoint.lease(runtime / broker_unix.LEASE_NAME):  # a broker that hangs
        with pytest.raises(TimeoutError):
            broker_unix.connect_or_spawn(
                root,
                "k",
                time.monotonic() + 0.5,
                lambda listener, lease: spawned.append(1),
            )
    assert spawned == []


def test_a_stale_socket_is_replaced_under_the_lease(root):
    runtime = broker_unix.runtime_directory(root, "k")
    stale = endpoint.listen(runtime / broker_unix.SOCKET_NAME)
    stale.close()  # the file stays, nobody listens: a crashed broker
    started: list[socket.socket] = []

    def spawn(listener, lease):
        started.append(socket.socket(fileno=os.dup(listener.fileno())))

    channel = broker_unix.connect_or_spawn(root, "k", time.monotonic() + 5, spawn)
    try:
        assert len(started) == 1
        accepted, _ = started[0].accept()
        accepted.close()
    finally:
        channel.close()
        started[0].close()


def test_a_root_too_long_for_sun_path_moves_the_socket_to_the_user_runtime_dir(
    root, monkeypatch
):
    deep = root / ("d" * 120)
    deep.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(root / "run"))
    base = broker_unix.socket_root(deep, "k")
    assert base == root / "run" / f"cortex-{os.geteuid()}"
    (root / "run").mkdir(mode=0o700)
    runtime = broker_unix.runtime_directory(base, "k")
    assert len(os.fsencode(str(runtime / broker_unix.SOCKET_NAME))) <= 103
    assert stat.S_IMODE(base.stat().st_mode) == 0o700
    assert broker_unix.socket_root(root, "k") == root  # short roots stay put


def test_a_runtime_base_owned_by_someone_else_is_refused(root, monkeypatch):
    base = root / "shared"
    base.mkdir(mode=0o777)
    base.chmod(0o777)  # writable by other users, as a squatted /tmp entry would be
    with pytest.raises(PermissionError, match="writable by other users"):
        broker_unix.runtime_directory(base, "k")
