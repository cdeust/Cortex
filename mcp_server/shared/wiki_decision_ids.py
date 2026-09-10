"""Canonical decision identity, independent of storage.

source: ADR-0677
"""

from __future__ import annotations

import re

_TOKEN = re.compile(r"ADR-([0-9]{4})")
_FILENAME = re.compile(r"([0-9]{4})-([A-Za-z0-9][A-Za-z0-9_.-]*)\.md")
# source: ADR-0677
MAX_DECISION_NUMBER = 9999
# source: ADR-0677
RESERVED_DECISION_NUMBER = 55


def parse_decision_id(text: str) -> int | None:
    """Accept only a complete canonical token, never prose or a substring."""
    match = _TOKEN.fullmatch(text)
    if match is None:
        return None
    number = int(match.group(1))
    return number if number else None


def decision_id(number: int) -> str:
    """Render a validated decision number without silently extending its width.

    source: ADR-0677
    """
    if isinstance(number, bool) or not isinstance(number, int):
        raise ValueError("decision number must be an integer")
    if not 1 <= number <= MAX_DECISION_NUMBER:
        raise ValueError("decision number must be between 1 and 9999")
    return f"ADR-{number:04d}"


def parse_decision_filename(filename: str) -> int | None:
    """Parse a complete NNNN-slug.md filename with a nonzero canonical ID."""
    match = _FILENAME.fullmatch(filename)
    if match is None:
        return None
    number = int(match.group(1))
    return number if number else None
