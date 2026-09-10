"""Bounded, one-request Unix stream framing; stdlib and injected policy only."""

from __future__ import annotations

import json
import socket
import struct
import time
from dataclasses import dataclass

# source: ADR-0513
_LENGTH = struct.Struct("!I")
_ACCEPTED = b"\x01"  # source: ADR-0513
_REFUSED = b"\x00"


@dataclass(frozen=True)
class Limits:
    """Composition supplies sourced transport and idle budgets."""

    max_bytes: int
    timeout: float
    idle: float


class CaptureTransportError(RuntimeError):
    """Capture was not confirmed admitted; do not retry uncertain delivery."""


def encode(payload: dict[str, object], max_bytes: int) -> bytes:
    body = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    if len(body) > max_bytes:
        raise CaptureTransportError("capture exceeds the transport envelope")
    return _LENGTH.pack(len(body)) + body


def remaining(deadline: float) -> float:
    budget = deadline - time.monotonic()
    if budget <= 0:
        raise TimeoutError("capture transport deadline exceeded")
    return budget


def _read_exact(connection: socket.socket, length: int, deadline: float) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        connection.settimeout(remaining(deadline))
        chunk = connection.recv(length - len(chunks))
        if not chunk:
            raise CaptureTransportError("incomplete capture frame")
        chunks.extend(chunk)
    return bytes(chunks)


def receive(
    connection: socket.socket, max_bytes: int, deadline: float
) -> dict[str, object]:
    length = _LENGTH.unpack(_read_exact(connection, _LENGTH.size, deadline))[0]
    if length > max_bytes:
        raise CaptureTransportError("capture frame length exceeds envelope")
    try:
        payload = json.loads(_read_exact(connection, length, deadline))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise CaptureTransportError("invalid capture JSON") from exc
    if not isinstance(payload, dict):
        raise CaptureTransportError("capture payload must be an object")
    return payload


def acknowledge(connection: socket.socket, accepted: bool) -> None:
    connection.sendall(_ACCEPTED if accepted else _REFUSED)


def send(connection: socket.socket, frame: bytes, deadline: float) -> None:
    connection.settimeout(remaining(deadline))
    connection.sendall(frame)
    if _read_exact(connection, len(_ACCEPTED), deadline) != _ACCEPTED:
        raise CaptureTransportError("worker refused capture admission")
