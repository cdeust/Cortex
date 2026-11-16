"""wiki_read's source trace: which memories, segments and versions a page rests on.

A page written with ``wiki_write(memory_ids=...)`` records one
``wiki.citations`` row per memory it was authored from. This module reads
those rows for the page wiki_read returns and resolves each memory through
``cited_memory_sources``, so a caller challenging a synthesis gets the
document segment and version behind it, and a reference whose memory is gone
comes back marked ``missing`` instead of disappearing.

The trace never blocks the read: the page content is filesystem-only and is
returned either way. When the trace cannot be built, the response says so in
``sources_unavailable`` rather than returning an empty list that would read
as "this page cites nothing".

source: issue #713 (slice 3)"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from mcp_server.core.document_reference import cited_memory_sources
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.pg_store_wiki import (
    get_page_by_rel_path,
    list_page_cited_memory_ids,
)

logger = logging.getLogger(__name__)

# source: issue #713 (slice 3) — the page file exists but no wiki.pages row
# was ever compiled for it, so there are no citations to read.
PAGE_NOT_INDEXED = "page_not_indexed"


def attach_page_sources(
    resp: dict[str, Any], rel_path: str, get_store: Callable[[], MemoryStore]
) -> dict[str, Any]:
    """Add ``sources`` (or ``sources_unavailable``) to a wiki_read response.

    precondition: rel_path is the wiki-relative path of the page whose
    content ``resp`` carries (the terminal page after redirects).
    postcondition: exactly one of ``sources`` (a list, possibly empty, in
    citation order) or ``sources_unavailable`` (a reason string) is set.
    Returns ``resp`` for chaining.
    """
    try:
        store = get_store()
        page = get_page_by_rel_path(store._conn, rel_path)
        if page is None:
            resp["sources_unavailable"] = PAGE_NOT_INDEXED
            return resp
        cited = list_page_cited_memory_ids(store._conn, int(page["id"]))
        memories = store.get_memories_by_ids(cited)
    except Exception as exc:  # noqa: BLE001 — mechanism boundary; failure is reported in the response and logged
        logger.warning("wiki_read source trace failed for %s", rel_path, exc_info=True)
        resp["sources_unavailable"] = f"{type(exc).__name__}: {exc}"
        return resp
    resp["sources"] = cited_memory_sources(cited, memories)
    return resp
