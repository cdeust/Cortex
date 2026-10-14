"""In-context injection markers and the session identity they key on.

Pure string functions shared by the receipt emitter (``handlers``) and the
hooks that render injected banners: a hook may import ``shared`` but not
``handlers`` (docs/module-inventory.md § Dependency Rules).

source: ADR-0417"""

from __future__ import annotations

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
