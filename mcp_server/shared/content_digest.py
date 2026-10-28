"""UTF-8 MD5 compatibility function for SQLite connections.

Exact replay lookup uses SQLite's native content index without this function.

The function supports callers of the connection's md5() compatibility function.
It is never a security primitive. PostgreSQL exact lookup hashes both operands
on the server and verifies full text, without assuming UTF-8 server encoding.
source: https://www.postgresql.org/docs/current/functions-string.html
"""

from __future__ import annotations

import hashlib


def content_digest(content: str) -> str:
    """Hash exact bytes without case folding or whitespace normalization."""
    return hashlib.md5(content.encode("utf-8"), usedforsecurity=False).hexdigest()
