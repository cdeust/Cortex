#!/usr/bin/env python3
"""Fuzz the store broker's frame decoder against its own contract.

Why this target
---------------
Every byte a client sends to the broker goes through
``broker_protocol.loads`` (JSON, then the tagged-value codec) and, for a
request, ``check_request`` before anything is dispatched. A decoder that
lets any other exception escape kills the connection thread with a stack
trace instead of a clean refusal, and a decoder that builds objects outside
its closed set of tags would turn a frame into code (ADR-1112, threat model,
tampering).

Property: for ANY bytes, ``loads`` returns a dict whose ``"t"`` is a string,
or raises ``ProtocolError``; for a returned request, ``check_request``
passes or raises ``ProtocolError``; nothing else escapes, and every value in
a decoded frame is of a type the codec can encode again.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server.infrastructure.broker_codec import encode  # noqa: E402
from mcp_server.infrastructure.broker_protocol import (  # noqa: E402
    ProtocolError,
    check_request,
    loads,
)


def consume(data: bytes) -> None:
    """One fuzz iteration. Shared by atheris and by replay_corpus.py."""
    try:
        message = loads(data)
    except ProtocolError:
        return
    if not isinstance(message, dict) or not isinstance(message.get("t"), str):
        raise AssertionError(f"loads returned {type(message).__name__} without a type")
    encode(message)  # every decoded value is inside the closed set
    if message["t"] == "req":
        try:
            check_request(message)
        except ProtocolError:
            return


def main() -> None:
    # Deferred, as in the other harnesses: atheris has no macOS or aarch64
    # wheel, and replay_corpus.py imports this module without a fuzzer.
    import atheris  # noqa: PLC0415

    atheris.Setup(sys.argv, consume)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
