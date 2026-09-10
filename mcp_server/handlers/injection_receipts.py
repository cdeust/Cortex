"""Injection-receipt emission for context-injecting channels.

source: ADR-0417"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mcp_server.infrastructure.pg_store_receipts import (
    insert_receipt_on_connection,
)

logger = logging.getLogger(__name__)

# source: ADR-0417
INJECTION_CHANNELS: frozenset[str] = frozenset(
    {"recall", "session_start", "auto_recall", "agent_briefing"}
)


def receipt_marker(receipt_id: int) -> str:
    """Render the in-context receipt marker (correction 2).

    source: ADR-0417"""
    return f"⟦rcpt:{receipt_id}⟧"


# Prefix of the per-memory fetch key below. Named so the one string has a
# single definition: renderers emit it, readers scan for it.
MEMORY_MARKER_PREFIX = "⟦mem:"


def memory_marker(memory_id: int) -> str:
    """Render the in-context fetch key for ONE truncated memory line.

        Same stance ``core/response_budget.py`` already takes for bounded MCP
        responses: "Truncated items ... keep their id, so truncation is never
        a dead end: full content stays dynamically loadable by id". Injected
        banner text was the one truncation path in the system that did not
        keep it, so its truncation WAS a dead end — the reader could see that
        a memory had been cut but had no handle to fetch the remainder, only
        a fresh search whose top hit is not guaranteed to be the same row.

    source: ADR-0417"""
    return f"{MEMORY_MARKER_PREFIX}{memory_id}⟧"


def session_id_from_transcript(transcript_path: object) -> str | None:
    """Derive the session identity from the transcript file name.

    source: ADR-0417"""
    if not isinstance(transcript_path, str) or not transcript_path:
        return None
    return Path(transcript_path).stem or None


def _build_items(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map an injected payload to receipt items, rank = injection order.

    source: ADR-0417"""
    return [
        {
            "memory_id": int(m["memory_id"]),
            "rank": rank,
            "score": None if m.get("score") is None else float(m["score"]),
        }
        for rank, m in enumerate(memories)
    ]


def _check_channel(channel: str) -> None:
    """Reject unknown channels loudly — a wrong channel is a coding bug."""
    if channel not in INJECTION_CHANNELS:
        raise ValueError(
            f"unknown injection channel {channel!r}; "
            f"expected one of {sorted(INJECTION_CHANNELS)}"
        )


def emit_injection_receipt(
    store: Any,
    memories: list[dict[str, Any]],
    *,
    channel: str = "recall",
    session_id: str | None = None,
) -> int | None:
    """Persist a receipt mirroring the bound payload; return receipt_id.

        Returns None — without failing the recall read path — when nothing
        was injected or when the receipt write fails (I/O is the only named
        degradation mode). Contract violations (unknown channel, missing
        memory_id) raise before any I/O is attempted.

    source: ADR-0417"""
    _check_channel(channel)
    if not memories:
        return None
    items = _build_items(memories)
    try:
        return store.insert_injection_receipt(
            channel=channel, items=items, session_id=session_id
        )
    except Exception:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("injection receipt emission failed", exc_info=True)
        return None


def emit_hook_receipt(
    conn: Any,
    memories: list[dict[str, Any]],
    *,
    channel: str,
    session_id: str | None,
) -> int | None:
    """Persist a receipt from a hook channel (T2); return receipt_id.

    Hooks own a short-lived psycopg connection and no store instance.
    Same parity invariant as ``emit_injection_receipt``: call with
    exactly the memories that will be printed to stdout — entries
    dropped by an injection budget were never in context; entries
    printed truncated keep their id and ARE in context.

    Same degradation contract: None on empty payload or receipt-write
    I/O failure (the hook keeps injecting its banner either way); loud
    raise on contract violations.
    """
    _check_channel(channel)
    if not memories:
        return None
    items = _build_items(memories)
    try:
        return insert_receipt_on_connection(
            conn, channel=channel, items=items, session_id=session_id
        )
    except Exception:  # noqa: BLE001 — last-resort boundary — failure is logged; degraded mode continues
        logger.warning("hook receipt emission failed", exc_info=True)
        return None
