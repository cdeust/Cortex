"""Persistent PostToolUse cadence, independent of one-shot hook processes.

All tool events count, including tools whose content is not captured. A
stable counter lock protects atomic JSON replacements. A separate,
non-blocking execution lock per Claude root serializes hook cascades without blocking
counter writers. Contention/failure leaves due work for a later event.

This is best effort, not exactly once: a crash after DB advancement but
before its acknowledgement can repeat advancement. It never resets due
work merely because another hook is executing a cascade. One invocation
attempts at most one pending interval, keeping catch-up work bounded.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from mcp_server.infrastructure.config import METHODOLOGY_DIR
from mcp_server.infrastructure.groomer_coordinator_io import (
    DecisionLock,
    atomic_write_json,
)
from mcp_server.infrastructure.hook_counter_lock import counter_lock

# source: post_tool_capture.py at 5de4f4a4; existing cadence preserved,
# empirical tuning provenance was not recorded at introduction.
CASCADE_INTERVAL = 20


def _session_directory(transcript_path: object) -> Path:
    """Use the same canonical transcript stem as injection_receipts.

    source: injection_receipts.session_id_from_transcript, decision 4255039
    correction 7 (148/200 fixture lines had a divergent event session_id).
    Do not import that handler here: it eagerly imports the PG stack.
    """
    if not isinstance(transcript_path, str) or not transcript_path.strip():
        raise ValueError("cascade skipped: missing transcript identity")
    identity = Path(transcript_path).stem
    if not identity or "\x00" in identity:
        raise ValueError("cascade skipped: invalid transcript identity")
    # Digest the identity, never interpret an external stem as a state path.
    key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return METHODOLOGY_DIR / "hook-cascade" / key


def _read_counter(directory: Path) -> dict[str, int]:
    try:
        state = json.loads((directory / "counter.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"tool_calls": 0, "completed": 0}
    if not isinstance(state, dict) or set(state) != {"tool_calls", "completed"}:
        raise ValueError("invalid cascade counter shape; state preserved")
    if any(type(value) is not int or value < 0 for value in state.values()):
        raise ValueError("invalid cascade counter values; state preserved")
    if (
        state["completed"] > state["tool_calls"]
        or state["completed"] % CASCADE_INTERVAL
    ):
        raise ValueError("invalid cascade counter progress; state preserved")
    return state


def _write_counter(directory: Path, state: dict[str, int]) -> None:
    if not atomic_write_json(directory / "counter.json", state):
        raise OSError("cascade counter write failed; advancement not acknowledged")


def _tick(directory: Path) -> bool:
    with counter_lock(directory / "counter.lock"):
        state = _read_counter(directory)
        state["tool_calls"] += 1
        _write_counter(directory, state)
        return state["tool_calls"] - state["completed"] >= CASCADE_INTERVAL


def _pending_deadline(directory: Path) -> int | None:
    with counter_lock(directory / "counter.lock"):
        state = _read_counter(directory)
        deadline = state["completed"] + CASCADE_INTERVAL
        return deadline if deadline <= state["tool_calls"] else None


def _acknowledge(directory: Path, deadline: int) -> None:
    with counter_lock(directory / "counter.lock"):
        state = _read_counter(directory)
        state["completed"] = deadline
        _write_counter(directory, state)


def advance_after_tool(transcript_path: object, advance: Callable[[], None]) -> str:
    """Count this event and attempt one due cascade; I/O errors propagate."""
    directory = _session_directory(transcript_path)
    if not _tick(directory):
        return "not_due"
    with DecisionLock(directory.parent / "cascade.lock") as acquired:
        if not acquired:
            return "pending"
        deadline = _pending_deadline(directory)
        if deadline is None:
            return "not_due"
        advance()
        _acknowledge(directory, deadline)
        return "advanced"
