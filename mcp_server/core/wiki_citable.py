"""Which memories a wiki page may record as the sources it rests on.

``wiki_write(memory_ids=...)`` records one ``wiki.citations`` row per
memory a page was authored from, and ``wiki_read`` traces the page back
through those rows (issue #713). A wiki pointer memory, the one
``wiki_write`` and ``wiki_adr`` register for every page so it surfaces in
``recall``, carries a prefix of a page's own markdown: it is a pointer,
never material to build a page from (``shared.wiki_pointer``, ADR-0475).
Recorded as a citation, it lets a derived page rest on itself (its own
pointer) or on another derived page that cites it back: a citation cycle.

Every memory derived from a page is such a pointer, so refusing pointers
as citations leaves no cycle through ``wiki.citations``. The refusal is
named in the response, never silent: a page that wanted to build on
another page cites the memories that page cites.

Pure: reads only the memory rows it is given.

source: issue #715 (slice 1, acceptance criterion 4); ADR-0475"""

from __future__ import annotations

from typing import Any

from mcp_server.shared.wiki_pointer import is_pointer_source

# source: issue #715 (slice 1) — the reason a refused citation carries: the
# memory's ``source`` is a ``wiki://`` page pointer (shared.wiki_pointer).
WIKI_POINTER = "wiki_pointer"


def split_citable(
    memory_ids: list[int], memories_by_id: dict[int, dict[str, Any]]
) -> tuple[list[int], list[dict[str, Any]]]:
    """Split the ids a page was authored from into citable and refused.

    precondition: ``memories_by_id`` holds the store rows of the ids it
    knows, each with its ``source`` column.
    postcondition: an id lands on one side only, in input order. An id
    whose row is a wiki pointer (``is_pointer_source``) is
    refused, once, as ``{"memory_id", "reason": "wiki_pointer"}``; every
    other id, including one the store does not hold, stays citable, so
    what this split decides is only the pointer rule.
    """
    citable: list[int] = []
    refused: list[dict[str, Any]] = []
    seen_refused: set[int] = set()
    for mid in memory_ids:
        mem = memories_by_id.get(mid)
        if mem is None or not is_pointer_source(mem.get("source")):
            citable.append(mid)
        elif mid not in seen_refused:
            seen_refused.add(mid)
            refused.append({"memory_id": mid, "reason": WIKI_POINTER})
    return citable, refused
