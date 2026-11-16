"""Forgetting a cited source names the wiki pages that rested on it.

A wiki page cites the memories it was written from (``wiki_write(memory_ids=
...)``). A soft ``forget`` keeps the memory and the page's trace marks it
``stale``; a hard ``forget`` erases the citation rows, so the page's trace
drops the memory and ``forget`` itself is the only place that says which pages
it was cited by. Neither path names a replacement location.

source: issue #713 (slice 4)
"""

from __future__ import annotations

import asyncio

from mcp_server.core.document_reference import cited_memory_sources
from mcp_server.handlers import forget, wiki_read
from tests_py.handlers.test_wiki_read_sources import _two_documents_and_a_page

_PAGE = "notes/key-rotation.md"


def test_retired_and_corrected_citations_are_marked_not_replaced():
    memories = {
        1: {"tags": [], "is_stale": True, "superseded_by_id": None},
        2: {"tags": [], "is_stale": False, "superseded_by_id": 9},
        3: {"tags": [], "is_stale": 0, "superseded_by_id": None},
    }
    assert cited_memory_sources([1, 2, 3], memories) == [
        {"memory_id": 1, "stale": True},
        {"memory_id": 2, "superseded_by_id": 9},
        {"memory_id": 3},
    ]


def _forget(memory_id: int, **flags) -> dict:
    # ingest_document protects its summaries, so the test forces the forget
    args = {"memory_id": memory_id, "force": True, **flags}
    return asyncio.run(forget.handler(args))


def _trace() -> list[dict]:
    page = asyncio.run(wiki_read.handler({"path": _PAGE}))
    assert "sources_unavailable" not in page
    return page["sources"]


def test_soft_forget_names_the_page_and_the_trace_marks_it_stale(monkeypatch, tmp_path):
    _, _, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    monkeypatch.setattr(forget, "_store", None)
    content = forget._get_store().get_memory(cited[0])["content"]
    assert len(content) > 80  # so the preview below is a real cut
    out = _forget(cited[0], soft=True)
    assert out["content_preview"] == content[:80]
    assert out["deleted"] is True and out["method"] == "soft"
    assert out["cited_by_pages"] == [_PAGE]
    trace = _trace()
    assert [ref["memory_id"] for ref in trace] == cited
    assert trace[0]["stale"] is True
    assert "stale" not in trace[1]


def test_hard_forget_names_the_page_whose_trace_loses_the_memory(monkeypatch, tmp_path):
    _, _, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    monkeypatch.setattr(forget, "_store", None)
    out = _forget(cited[0])
    assert out["deleted"] is True and out["method"] == "hard"
    assert out["cited_by_pages"] == [_PAGE]
    assert [ref["memory_id"] for ref in _trace()] == cited[1:]


def test_each_forget_of_a_cited_memory_names_its_page(monkeypatch, tmp_path):
    _, _, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    monkeypatch.setattr(forget, "_store", None)
    assert _forget(cited[0])["cited_by_pages"] == [_PAGE]
    # the same id again: the row is gone, so is the citation
    assert _forget(cited[0])["reason"] == "not_found"
    assert _forget(cited[1], soft=True)["cited_by_pages"] == [_PAGE]
