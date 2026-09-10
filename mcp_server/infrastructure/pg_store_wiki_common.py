"""Shared helpers for the wiki-schema store modules.

Pure infrastructure — no core imports, no handler imports.

source: ADR-0574"""

from __future__ import annotations

import hashlib
from typing import Any


def body_hash(body: str) -> str:
    """Deterministic hash of a page body — drives idempotent upserts."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _returning_id(row: dict[str, Any] | tuple[Any, ...] | None) -> int:
    """Extract the id from an ``INSERT ... RETURNING id`` fetchone() result.

    source: ADR-0574"""
    if row is None:
        raise RuntimeError("INSERT ... RETURNING id produced no row")
    return row["id"] if isinstance(row, dict) else row[0]
