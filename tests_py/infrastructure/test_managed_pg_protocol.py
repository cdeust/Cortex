"""managed_pg_protocol against hostile servers: nothing but this cluster passes.

PR #748's round-4 review, N1: the server-signature and nonce checks were
right but untested, and mutants removing either survived the suite. Each
server below misbehaves in one way; every one must end in ``ProtocolError``
before AuthenticationOk is accepted, and the password must never travel.
The servers are threads on loopback; the client returns or raises on the
server's bytes, nothing waits on a clock.

source: ADR-1114
source: https://www.rfc-editor.org/rfc/rfc5802 (SCRAM), rfc7677 (SHA-256)
"""

from __future__ import annotations

import base64
import secrets
import socket
import struct
import threading

import pytest

from mcp_server.infrastructure import managed_pg_protocol as protocol

# A fresh random password per run, as initdb's password file holds: no secret
# material in source (HOL plugin scan, HARDCODED_SECRET). source: ADR-1114
_PASSWORD = secrets.token_hex(24)
_SALT = base64.b64encode(b"salt").decode()  # source: test value


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


def _auth(code: int, body: bytes = b"") -> tuple[bytes, bytes]:
    return b"R", struct.pack("!i", code) + body


def _behave(conn: socket.socket, mode: str, seen: list[bytes]) -> None:
    (length,) = struct.unpack("!i", _read(conn, 4))
    _read(conn, length - 4)  # the startup packet
    if mode == "trust":  # AuthenticationOk without any exchange
        _send(conn, *_auth(0))
        _send(conn, b"Z", b"I")
        return
    if mode == "cleartext":  # AuthenticationCleartextPassword
        _send(conn, *_auth(3))
        seen.append(_message(conn))
        return
    _send(conn, *_auth(10, b"SCRAM-SHA-256\0\0"))
    first = _message(conn)
    seen.append(first)
    bare = first[first.index(b"\0") + 5 :].decode()[3:]
    nonce = dict(item.split("=", 1) for item in bare.split(","))["r"]
    served = {
        "badnonce": f"r=another-nonce,s={_SALT},i=4096",
        "nosalt": f"r={nonce}srv,i=4096",
    }.get(mode, f"r={nonce}srv,s={_SALT},i=4096")
    _send(conn, *_auth(11, served.encode()))
    seen.append(_message(conn))
    # badsig: a server without the verifier cannot compute the signature
    _send(conn, *_auth(12, b"v=" + base64.b64encode(b"x" * 32)))
    _send(conn, *_auth(0))
    _send(conn, b"Z", b"I")
    seen.append(_message(conn))


def _hostile(mode: str) -> tuple[int, list[bytes], threading.Thread]:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    seen: list[bytes] = []

    def serve() -> None:
        with listener:
            conn, _ = listener.accept()
            with conn:
                try:
                    _behave(conn, mode, seen)
                except (EOFError, OSError):
                    pass  # the client hung up, which is what it should do

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return listener.getsockname()[1], seen, thread


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("badsig", "signature is not this cluster's"),
        ("badnonce", "nonce does not extend ours"),
        ("trust", "expected authentication step 10"),
        ("cleartext", "expected authentication step 10"),
        ("nosalt", "malformed SCRAM server-first-message"),
    ],
)
def test_a_hostile_server_is_refused_and_never_gets_the_password(mode, reason):
    port, seen, thread = _hostile(mode)
    with pytest.raises(protocol.ProtocolError, match=reason):
        protocol.authenticate("127.0.0.1", port, "postgres", _PASSWORD)
    thread.join()  # ended by the client's hang-up, an event
    assert not any(_PASSWORD.encode() in message for message in seen)
    if mode == "cleartext":
        assert seen == [] or not seen[0].startswith(b"p")  # no password message
