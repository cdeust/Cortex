"""Injection-receipt emission for context-injecting channels.

Blame path T1/T2 (decision Cortex 4255039): every channel that injects
memory content into a context emits an append-only receipt at injection
time — the presence-in-context evidence the blame path resolves against.
T1 wired the recall channel; T2 wires the hook channels (session_start,
auto_recall, agent_briefing) and hardens the channel enum.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mcp_server.infrastructure.pg_store_receipts import (
    insert_receipt_on_connection,
)

logger = logging.getLogger(__name__)

# Hardened channel enum (T2, decision 4255039 correction 3): the four
# channels that inject memory content into a context. agent_briefing
# (SubagentStart) was the forgotten fourth channel flagged by the jury.
# The DDL CHECK constraints in pg_schema.py / sqlite_schema.py mirror
# these values — parity is asserted by test, not by convention.
INJECTION_CHANNELS: frozenset[str] = frozenset(
    {"recall", "session_start", "auto_recall", "agent_briefing"}
)


def receipt_marker(receipt_id: int) -> str:
    """Render the in-context receipt marker (correction 2).

    The marker travels INSIDE the injected text so the model can later
    pass the receipt id back to ``cortex:why(receipt_ids=[...])`` — the
    receipt-based primary path; server-side session-temporal resolution
    does not exist in MCP.
    """
    return f"⟦rcpt:{receipt_id}⟧"


def session_id_from_transcript(transcript_path: object) -> str | None:
    """Derive the session identity from the transcript file name.

    Decision 4255039 correction 7: the hook event's ``session_id`` field
    diverges from the transcript identity across resume/clear chains
    (verified 148/200 lines on fixture 7374abf5). The transcript file
    basename is the stable identity; when no transcript_path is present
    the honest value is None (session_id is NULLable by design).

    The hook event is EXTERNAL input (system boundary) — a malformed
    transcript_path of any non-string type degrades to None rather than
    raising into the hook's primary injection path.
    """
    if not isinstance(transcript_path, str) or not transcript_path:
        return None
    return Path(transcript_path).stem or None


def _build_items(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map an injected payload to receipt items, rank = injection order.

    Internal contract, trusted here: every injected entry carries an
    int-coercible ``memory_id``. A missing id is an upstream programming
    bug and MUST raise loudly: swallowing it would silently drop
    receipts in production and hide the regression.
    """
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

    Must be called AFTER bound_payload (transcript↔DB parity invariant,
    decision 4255039): entries dropped by the response budget were never
    injected; truncated entries keep their id and ARE in context.
    ``rank`` = index in the injected payload (0 = top result), persisted
    verbatim — blame ordering replays recorded facts only.

    Returns None — without failing the recall read path — when nothing
    was injected or when the receipt write fails (I/O is the only named
    degradation mode). Contract violations (unknown channel, missing
    memory_id) raise before any I/O is attempted.
    """
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
