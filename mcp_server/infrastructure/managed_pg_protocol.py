"""Prove a PostgreSQL server is the managed cluster: SCRAM-SHA-256 with its password.

Stdlib only. ``authenticate`` speaks the frontend/backend protocol 3.0 just far
enough to finish authentication: a startup packet, a SCRAM-SHA-256 exchange
(RFC 5802/7677) in which the client also verifies the server's signature, then
``ReadyForQuery``. Success proves three things at once: something speaking
PostgreSQL listens on the port, it holds the verifier ``initdb --pwfile``
derived from this cluster's password file (a foreign server cannot sign the
exchange), and it accepts connections (a starting server answers SQLSTATE
57P03 instead).

It is only ever called for a port held by a postmaster whose PID the kernel
already proved to be ours (``managed_pg_server``), so a silent foreign
listener is never dialled and no read here needs a timer.

source: ADR-1110
source: https://www.postgresql.org/docs/18/protocol-flow.html
source: https://www.rfc-editor.org/rfc/rfc5802 (SCRAM), rfc7677 (SHA-256)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import socket
import struct

_PROTOCOL = 196608  # source: protocol-message-formats, StartupMessage (3.0)
_AUTH_OK, _SASL, _SASL_CONTINUE, _SASL_FINAL = 0, 10, 11, 12  # source: same page
_MECHANISM = b"SCRAM-SHA-256"  # source: RFC 7677
_NONCE_BYTES = 18  # source: libpq fe-auth-scram.c SCRAM_RAW_NONCE_LEN


class ProtocolError(RuntimeError):
    """The server did not authenticate as the managed cluster; the message says why."""


def _read(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ProtocolError("the server closed the connection")
        data += chunk
    return data


def _message(sock: socket.socket) -> tuple[bytes, bytes]:
    """The next backend message ``(type, body)``; an ErrorResponse raises."""
    kind = _read(sock, 1)
    (length,) = struct.unpack("!i", _read(sock, 4))
    body = _read(sock, length - 4)
    if kind == b"E":
        fields = dict(
            (part[:1], part[1:].decode("utf-8", "replace"))
            for part in body.split(b"\0")
            if part
        )
        code, text = fields.get(b"C", "?"), fields.get(b"M", repr(body))
        raise ProtocolError(f"{code}: {text}")
    return kind, body


def _send(sock: socket.socket, kind: bytes, body: bytes) -> None:
    sock.sendall(kind + struct.pack("!i", len(body) + 4) + body)


def _auth(sock: socket.socket, expected: int) -> bytes:
    """The rest of the next Authentication message, whose code must be ``expected``."""
    while True:
        kind, body = _message(sock)
        if kind in (b"N", b"v"):  # a notice, or a protocol-version negotiation
            continue
        code = struct.unpack("!i", body[:4])[0] if kind == b"R" else None
        if code != expected:
            raise ProtocolError(
                f"expected authentication step {expected}, got {kind!r} {code}"
            )
        return body[4:]


def _hmac(key: bytes, text: bytes) -> bytes:
    return hmac.new(key, text, hashlib.sha256).digest()


def _scram(sock: socket.socket, password: str) -> None:
    if _MECHANISM not in _auth(sock, _SASL).split(b"\0"):
        raise ProtocolError("the server does not offer SCRAM-SHA-256")
    nonce = base64.b64encode(secrets.token_bytes(_NONCE_BYTES)).decode()
    first_bare = f"n=,r={nonce}"
    first = f"n,,{first_bare}".encode()
    _send(sock, b"p", _MECHANISM + b"\0" + struct.pack("!i", len(first)) + first)
    server_first = _auth(sock, _SASL_CONTINUE).decode()
    attrs = dict(item.split("=", 1) for item in server_first.split(","))
    if not attrs.get("r", "").startswith(nonce):
        raise ProtocolError("the server's SCRAM nonce does not extend ours")
    salted = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), base64.b64decode(attrs["s"]), int(attrs["i"])
    )
    client_key = _hmac(salted, b"Client Key")
    without_proof = f"c=biws,r={attrs['r']}"
    message = f"{first_bare},{server_first},{without_proof}".encode()
    signature = _hmac(hashlib.sha256(client_key).digest(), message)
    proof = bytes(a ^ b for a, b in zip(client_key, signature, strict=True))
    final = f"{without_proof},p={base64.b64encode(proof).decode()}"
    _send(sock, b"p", final.encode())
    verifier = _auth(sock, _SASL_FINAL).decode()
    expected = base64.b64encode(_hmac(_hmac(salted, b"Server Key"), message)).decode()
    if not hmac.compare_digest(verifier, f"v={expected}"):
        raise ProtocolError("the server's SCRAM signature is not this cluster's")


def authenticate(host: str, port: int, user: str, password: str) -> None:
    """Return once ``host:port`` authenticated ``user`` with ``password`` and is ready.

    Raises ``ProtocolError`` (or ``OSError`` from the connection) otherwise.
    """
    with socket.create_connection((host, port)) as sock:
        params = f"user\0{user}\0database\0postgres\0\0".encode()
        body = struct.pack("!i", _PROTOCOL) + params
        sock.sendall(struct.pack("!i", len(body) + 4) + body)
        _scram(sock, password)
        _auth(sock, _AUTH_OK)
        while _message(sock)[0] != b"Z":  # ParameterStatus, BackendKeyData, ...
            continue
        _send(sock, b"X", b"")
