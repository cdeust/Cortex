"""wiki_read's source trace: which memories, segments and versions a page rests on.

A page written with ``wiki_write(memory_ids=...)`` records one
``wiki.citations`` row per memory it was authored from. This module reads
those rows for the page wiki_read returns and resolves each memory through
``cited_memory_sources``, so a caller challenging a synthesis gets the
document segment and version behind it. A cited id the store no longer
resolves comes back marked ``missing``. A memory deleted from the store loses
its citation link in the database (``ON DELETE SET NULL``, or the row removed by
a hard ``forget``), so it no longer appears here; reporting the references a
deletion touched is issue #713 slice 4.

The page content keeps priority over the trace in the response budget:
``fit_sources`` drops trace entries from the tail, and says so, before the
content is cut.

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
from mcp_server.core.response_budget import serialized_length
from mcp_server.infrastructure.memory_store import MemoryStore
from mcp_server.infrastructure.pg_store_wiki import (
    get_page_by_rel_path,
    list_page_cited_memory_ids,
)

logger = logging.getLogger(__name__)

# source: issue #713 (slice 3) — the page file exists but no wiki.pages row
# was ever compiled for it, so there are no citations to read.
PAGE_NOT_INDEXED = "page_not_indexed"
# source: issue #713 (slice 3), review of PR #1078 — the store error itself can
# carry the database URL and its password (memory_store._construct_store), so
# the response names only the class of failure; the log keeps the detail.
STORE_ERROR = "store_error"


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
    except Exception:  # noqa: BLE001 — mechanism boundary; failure is reported in the response and logged
        logger.warning("wiki_read source trace failed for %s", rel_path, exc_info=True)
        resp["sources_unavailable"] = STORE_ERROR
        return resp
    resp["sources"] = cited_memory_sources(cited, memories)
    return resp


def fit_sources(resp: dict[str, Any], budget_chars: int) -> None:
    """Drop ``sources`` entries from the tail until the content fits beside them.

    postcondition: the trace never takes space the content needs. When the
    content alone exceeds the budget every entry is dropped; paging by
    ``offset`` shrinks the content and leaves the trace more room. A trace
    that does not fit beside the response's other fields even with no
    content stays cut at every offset. On any drop, ``sources_truncated`` is
    true and ``sources_total`` gives the full count.

    complexity: the response is serialized twice, then each dropped entry
    alone, so the cut is linear in the size of the response.
    """
    sources = resp.get("sources")
    if not isinstance(sources, list) or not sources:
        return
    if serialized_length(resp) <= budget_chars:
        return
    # the flags are set before the cut so their own length is counted in it
    resp["sources_truncated"] = True
    resp["sources_total"] = len(sources)
    # one serialization of the whole response, then exact compact-JSON
    # arithmetic per dropped entry: while another entry remains, removing the
    # last one removes it and the comma before it. The size left after the only
    # remaining entry goes is never read: the loop ends on the empty list.
    size = serialized_length(resp)
    while sources and size > budget_chars:
        size -= serialized_length(sources.pop()) + 1
