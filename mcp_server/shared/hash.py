"""Non-cryptographic DJB2 hash function for content fingerprinting.

Generates fast, deterministic 32-bit fingerprints for text content.
Only the first 500 characters are hashed to bound computation time.
"""

from __future__ import annotations


def simple_hash(text: str | None) -> str:
    """Compute a 32-bit DJB2 hash of the first 500 characters of text.

    Returns a lowercase hexadecimal string.
    """
    s = (text or "")[:500]
    h = 5381
    for ch in s:
        h = ((h << 5) + h + ord(ch)) & 0xFFFFFFFF
    return format(h, "x")
