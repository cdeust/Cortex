"""In-context injection markers and the session identity they key on.

Pure string functions shared by the receipt emitter (``handlers``) and the
hooks that render injected banners: a hook may import ``shared`` but not
``handlers`` (docs/module-inventory.md § Dependency Rules).

source: ADR-0417"""

from __future__ import annotations

import hashlib
from pathlib import Path


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


def session_end_event_id(session_id: str, transcript_path: object) -> str:
    """Identity of one SessionEnd delivery: the session and the file it closes.

    Codex continues one logical session into a second rollout file (#716).
    Keyed on ``session_id`` alone, the second file's SessionEnd was taken for
    a replay of the first and dropped. A replay of the same file keeps its
    identity; an event with no transcript is keyed on the session alone. The
    Codex intake (``plugins/hypermnesia-mcp-codex/scripts/session_queue.py``
    ``job_key``) computes the same value without importing ``mcp_server``.

    source: ADR-1141"""
    stem = session_id_from_transcript(transcript_path)
    text = session_id if stem is None else f"{session_id}\0{stem}"
    return hashlib.sha256(text.encode()).hexdigest()
