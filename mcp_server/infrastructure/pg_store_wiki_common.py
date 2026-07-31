"""Shared helpers for the wiki-schema store modules.

Split out of ``pg_store_wiki.py`` (originally 890 lines, over the
300-line file limit — CLAUDE.md "Code Quality Rules") purely for size
compliance; no logic changed. ``body_hash`` and ``_returning_id`` are
used across the pages/claims/concepts/drafts/citations modules.

Pure infrastructure — no core imports, no handler imports.
"""

from __future__ import annotations

import hashlib
from typing import Any


def body_hash(body: str) -> str:
    """Deterministic hash of a page body — drives idempotent upserts."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _returning_id(row: dict[str, Any] | tuple[Any, ...] | None) -> int:
    """Extract the id from an ``INSERT ... RETURNING id`` fetchone() result.

    A default psycopg cursor yields tuple rows; a ``dict_row`` cursor yields
    dict rows — hence the isinstance split. An INSERT ... RETURNING always
    produces exactly one row, so a None here is a broken query (or a silently
    rolled-back transaction), not a normal path — surface it loudly.
    """
    if row is None:
        # This IS the canonical, multi-call-site-shared construction point
        # (pages/claims/concepts/drafts/citations modules) this helper
        # exists to be — not a one-off (§3.3).
        raise RuntimeError("INSERT ... RETURNING id produced no row")  # noqa: TRY003
    return row["id"] if isinstance(row, dict) else row[0]
