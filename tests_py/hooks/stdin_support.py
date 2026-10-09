"""Test double for the hook event on stdin: UTF-8 bytes behind a text wrapper.

Hooks read ``sys.stdin.buffer`` (``mcp_server.hooks.stdin_event``), so a test
that feeds an event must supply a real binary buffer, as the host's pipe does.
"""

from __future__ import annotations

import io


def utf8_stdin(text: str) -> io.TextIOWrapper:
    """A ``sys.stdin`` stand-in whose bytes are ``text`` encoded as UTF-8."""
    return io.TextIOWrapper(io.BytesIO(text.encode("utf-8")), encoding="utf-8")
