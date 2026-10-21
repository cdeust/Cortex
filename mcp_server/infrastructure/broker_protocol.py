"""Broker wire protocol: framed JSON messages over a local byte channel.

One frame is a four-byte network-order length and one UTF-8 JSON object
(the capture protocol, ADR-0513), checked against a size limit before any
allocation. A connection starts with ``hello``/``welcome`` (protocol
version, code revision, schema version, client kind), then carries
request/response pairs in order: a client sends one request and waits for
its response, so a connection never has two requests in flight.

    {"t": "req", "id": 7, "kind": "method", "name": "recall_memories",
     "args": [...], "kwargs": {...}, "class": "interactive", "deadline": 29.5}
    {"t": "res", "id": 7, "ok": true, "v": ...}
    {"t": "res", "id": 7, "ok": false, "error": {"type": "...", "message": "..."}}

``kind`` is ``"method"`` (an allowlisted store method) or ``"op"`` (a marked
store operation, ``module:function``). No SQL text is ever part of a
request.

source: ADR-1112 (broker and versioned schema)
"""

from __future__ import annotations

import json
import struct
import time
from typing import Any, Protocol

from mcp_server.infrastructure.broker_codec import decode, encode

# source: ADR-1112 bumped on any incompatible message change
PROTOCOL_VERSION = 1
# source: ADR-0513 the capture frame header (four-byte network-order length)
_LENGTH = struct.Struct("!I")
# source: ADR-1112 request cap: 64 x the 1 MiB content envelope (CONTENT_MAX_BYTES)
MAX_REQUEST_BYTES = 64 * 1024 * 1024
# source: ADR-1112 response cap: whole-corpus reads (e.g. get_all_entities)
MAX_RESPONSE_BYTES = 1024 * 1024 * 1024
REQUEST_CLASSES = ("interactive", "background")


class ProtocolError(RuntimeError):
    """A malformed, oversized or unexpected frame; the connection is closed."""


class Channel(Protocol):
    """A connected, authenticated local byte stream."""

    def send_bytes(self, data: bytes) -> None: ...

    def recv_bytes(self, limit: int, deadline: float | None) -> bytes: ...

    def close(self) -> None: ...


def dumps(message: dict[str, Any]) -> bytes:
    return json.dumps(encode(message), separators=(",", ":")).encode("utf-8")


def loads(data: bytes) -> dict[str, Any]:
    try:
        message = decode(json.loads(data))
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
        # CodecError is a ValueError; a tagged object with missing or
        # mistyped fields raises KeyError or TypeError while it is rebuilt
        raise ProtocolError(f"invalid frame: {type(exc).__name__}: {exc}") from exc
    if not isinstance(message, dict) or not isinstance(message.get("t"), str):
        raise ProtocolError("a frame must be an object with a type")
    return message


def frame(data: bytes, limit: int) -> bytes:
    if len(data) > limit:
        raise ProtocolError(f"frame of {len(data)} bytes exceeds {limit}")
    return _LENGTH.pack(len(data)) + data


def frame_length(header: bytes, limit: int) -> int:
    (length,) = _LENGTH.unpack(header)
    if length > limit:
        raise ProtocolError(f"frame of {length} bytes exceeds {limit}")
    return length


HEADER_SIZE = _LENGTH.size


def remaining(deadline: float | None) -> float | None:
    """Seconds left before ``deadline`` (monotonic), None for no deadline."""
    if deadline is None:
        return None
    left = deadline - time.monotonic()
    if left <= 0:
        raise TimeoutError("broker deadline exceeded")
    return left


def check_request(message: dict[str, Any]) -> None:
    """Shape of a request, checked before anything is dispatched."""
    if message.get("t") != "req":
        raise ProtocolError("expected a request")
    if not isinstance(message.get("id"), int):
        raise ProtocolError("a request needs an integer id")
    if message.get("kind") not in ("method", "op"):
        raise ProtocolError("unknown request kind")
    if not isinstance(message.get("name"), str):
        raise ProtocolError("a request needs a name")
    if not isinstance(message.get("args"), list) or not isinstance(
        message.get("kwargs"), dict
    ):
        raise ProtocolError("args must be a list and kwargs an object")
    if message.get("class") not in REQUEST_CLASSES:
        raise ProtocolError("unknown request class")
    deadline = message.get("deadline")
    if not isinstance(deadline, (int, float)) or deadline <= 0:
        raise ProtocolError("a request needs a positive deadline in seconds")
