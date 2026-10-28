"""Exact UTF-8 content identity, compatible with PostgreSQL md5(text).

The digest selects candidates; byte equality remains mandatory because MD5
is not collision resistant. This is an index key, never a security primitive.
source: https://www.postgresql.org/docs/current/functions-binarystring.html
"""

from __future__ import annotations

import hashlib


def content_digest(content: str) -> str:
    """Hash exact bytes without case folding or whitespace normalization."""
    return hashlib.md5(content.encode("utf-8"), usedforsecurity=False).hexdigest()
