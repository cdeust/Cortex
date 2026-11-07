"""A stand-in ``bin/postgres`` for the managed server's tests (ADR-1114).

Run as ``postgres -D <cluster> -p <port>`` it behaves as far as the supervisor
can observe: it writes ``postmaster.pid`` the way PostgreSQL does (5 lines,
then the listen address and shared-memory key, then ``starting``, then
``ready``), listens on 127.0.0.1, completes a real SCRAM-SHA-256 exchange
against ``<cluster>/../password`` (so ``managed_pg_protocol`` is exercised end
to end), sends ``ReadyForQuery``, and on SIGINT removes ``postmaster.pid`` and
exits 0, as it does once its test's lifeline is released
(``FAKE_PG_LIFELINE``). ``FAKE_PG_FAIL=<text>`` makes it print the text and
exit 1 instead. Line 3 of ``postmaster.pid`` is the start time, as in PG.
Every connection is appended to ``<cluster>/../connections.log``.

source: ADR-1114 (test double of the postmaster the supervisor spawns)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import signal
import socket
import struct
import sys
import threading
import time
from pathlib import Path

_ITERATIONS = 4096  # source: PostgreSQL scram_iterations default
_SALT = b"cortex-fake-salt"  # source: test value


def install(bin_dir: Path) -> Path:
    """Write ``bin_dir/postgres`` running this module; return it."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "postgres"
    me = str(Path(__file__))
    script.write_text(
        f"#!{sys.executable}\nimport runpy, sys\nsys.argv[0] = {me!r}\n"
        f"runpy.run_path({me!r}, run_name='__main__')\n"
    )
    script.chmod(0o755)
    return script


def _read(conn: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise EOFError
        data += chunk
    return data


def _message(conn: socket.socket) -> bytes:
    _read(conn, 1)
    (length,) = struct.unpack("!i", _read(conn, 4))
    return _read(conn, length - 4)


def _send(conn: socket.socket, kind: bytes, body: bytes) -> None:
    conn.sendall(kind + struct.pack("!i", len(body) + 4) + body)


def _hmac(key: bytes, text: bytes) -> bytes:
    return hmac.new(key, text, hashlib.sha256).digest()


def _serve(conn: socket.socket, password: str) -> None:
    with conn:
        (length,) = struct.unpack("!i", _read(conn, 4))
        _read(conn, length - 4)  # the startup packet
        _send(conn, b"R", struct.pack("!i", 10) + b"SCRAM-SHA-256\0\0")
        initial = _message(conn)
        first = initial[initial.index(b"\0") + 5 :].decode()
        first_bare = first[3:]
        nonce = dict(i.split("=", 1) for i in first_bare.split(","))["r"] + "srv"
        server_first = f"r={nonce},s={base64.b64encode(_SALT).decode()},i={_ITERATIONS}"
        _send(conn, b"R", struct.pack("!i", 11) + server_first.encode())
        final = _message(conn).decode()
        without_proof, _, proof = final.rpartition(",p=")
        salted = hashlib.pbkdf2_hmac("sha256", password.encode(), _SALT, _ITERATIONS)
        message = f"{first_bare},{server_first},{without_proof}".encode()
        client_key = _hmac(salted, b"Client Key")
        signature = _hmac(hashlib.sha256(client_key).digest(), message)
        expected = bytes(a ^ b for a, b in zip(client_key, signature, strict=True))
        if base64.b64decode(proof) != expected:
            error = b"SFATAL\0C28P01\0Mpassword authentication failed\0\0"
            _send(conn, b"E", error)
            return
        verifier = base64.b64encode(_hmac(_hmac(salted, b"Server Key"), message))
        _send(conn, b"R", struct.pack("!i", 12) + b"v=" + verifier)
        _send(conn, b"R", struct.pack("!i", 0))
        _send(conn, b"Z", b"I")
        try:
            _message(conn)  # Terminate
        except EOFError:
            pass


def _follow_lifeline(lock: Path) -> None:
    """Exit once the test that owns this fake released its lifeline lock
    (``fake_pg_lifeline``): on any end of the test process, including a kill
    or ``os._exit``, the kernel releases it. An event, never a timer."""
    path = os.environ.get("FAKE_PG_LIFELINE")
    if not path:
        return
    import fcntl  # noqa: PLC0415 — POSIX only, like the managed server

    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)

    def wait() -> None:
        fcntl.flock(fd, fcntl.LOCK_SH)  # granted when the test's EX is gone
        lock.unlink(missing_ok=True)
        os._exit(0)

    threading.Thread(target=wait, daemon=True).start()


def main(argv: list[str]) -> None:
    cluster = Path(argv[argv.index("-D") + 1])
    port = int(argv[argv.index("-p") + 1])
    failure = os.environ.get("FAKE_PG_FAIL")
    if failure:
        print(failure, file=sys.stderr, flush=True)
        sys.exit(1)
    lock = cluster / "postmaster.pid"

    def stop(*_args) -> None:
        lock.unlink(missing_ok=True)
        os._exit(0)

    # Before postmaster.pid exists, as PostgreSQL's PostmasterMain does: a
    # SIGINT inherited as ignored (a background shell job) must not be lost.
    signal.signal(signal.SIGINT, stop)
    _follow_lifeline(lock)
    # line 3 is MyStartTime, time(NULL) after exec, as PostgreSQL writes it
    base = f"{os.getpid()}\n{cluster}\n{int(time.time())}\n{port}\n\n"
    lock.write_text(base)
    listener = socket.socket()
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen()
    lock.write_text(base + "127.0.0.1\n1 2\nstarting\n")
    lock.write_text(base + "127.0.0.1\n1 2\nready   \n")

    password = (cluster.parent / "password").read_text().strip()
    log = cluster.parent / "connections.log"
    while True:
        conn, _ = listener.accept()
        with log.open("a") as handle:
            handle.write("connection\n")
        threading.Thread(target=_serve, args=(conn, password), daemon=True).start()


if __name__ == "__main__":
    main(sys.argv[1:])
