"""Capture sources: the ``source`` values Cortex's own capture writers set.

Default recall and trigger injection hide a memory a Cortex writer recorded
by itself (a tool-output capture, a bulk backfill or import, a codebase seed,
a session summary). Each of those writers sets ``source`` in the arguments it
passes to ``remember``; the user never picks it through a tag. This module is
the one list of those values, so the filter keys on the marker the system
writes and never on a word a user may choose (issue #706).

Writers, read on main at db035d8:

- ``post_tool_capture``: ``hooks/post_tool_capture.py`` and
  ``hooks/capture_worker_policy.py`` (tool-output captures, write class auto);
- ``backfill:<slug>``: ``handlers/backfill_memories.py``;
- ``import``: ``handlers/import_sessions.py``;
- ``seed:<rel>``: ``handlers/wiki_seed_codebase.py``;
- ``session``: ``handlers/record_session_end_memory.py``.

source: ADR-1140 (keys the filter on source), ADR-0431 (the filter)
"""

from __future__ import annotations

# source: ADR-1140 -- the exact sources listed in the module docstring.
CAPTURE_SOURCES: frozenset[str] = frozenset({"post_tool_capture", "import", "session"})

# source: ADR-1140 -- per-item sources of the backfill and seed writers.
CAPTURE_SOURCE_PREFIXES: tuple[str, ...] = ("backfill:", "seed:")


def is_capture_source(source: object) -> bool:
    """Whether ``source`` names one of Cortex's own capture writers.

    Precondition: ``source`` is the ``source`` field of a memory, or None.
    Postcondition: True only for a value in CAPTURE_SOURCES or one that
    starts with a CAPTURE_SOURCE_PREFIXES entry; tags are never read.
    source: ADR-1140"""
    if not isinstance(source, str):
        return False
    return source in CAPTURE_SOURCES or source.startswith(CAPTURE_SOURCE_PREFIXES)
