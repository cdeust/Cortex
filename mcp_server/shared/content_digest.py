"""Exact UTF-8 candidate hashing for SQLite lookups.

The digest selects candidates; byte equality remains mandatory because MD5
is not collision resistant. This is an index key, never a security primitive.
PostgreSQL hashes both operands on the server, so server encoding is not assumed.
source: https://www.postgresql.org/docs/current/functions-string.html
"""

from __future__ import annotations

import hashlib


def content_digest(content: str) -> str:
    """Hash exact bytes without case folding or whitespace normalization."""
    return hashlib.md5(content.encode("utf-8"), usedforsecurity=False).hexdigest()
