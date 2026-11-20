"""wiki_read says whether a memory-derived page still matches its sources.

source: issue #715 (slice 2, acceptance criterion 3)
"""

from __future__ import annotations

import asyncio

from mcp_server.core.wiki_page_freshness import (
    PAGE_CURRENT,
    PAGE_FAILED,
    PAGE_PENDING,
    page_freshness,
)
from mcp_server.handlers import forget, wiki_read
from mcp_server.handlers.wiki_read_sources import fit_sources
from tests_py.handlers.test_wiki_read_sources import _two_documents_and_a_page

_PAGE = "notes/key-rotation.md"


def test_each_changed_citation_makes_the_page_pending_in_citation_order():
    sources = [
        {"memory_id": 4},
        {"memory_id": 9, "stale": True},
        {"memory_id": 2, "superseded_by_id": 11},
        {"memory_id": 7, "missing": True},
    ]
    assert page_freshness(sources, record_matches_text=True) == {
        "state": PAGE_PENDING,
        "record_matches_text": True,
        "pending_memory_ids": [9, 2, 7],
        "frontier": {"cited_memories": 4, "max_memory_id": 9},
    }


def test_live_citations_and_no_citation_are_current():
    live = [{"memory_id": 3}, {"memory_id": 5}]
    assert page_freshness(live, record_matches_text=True)["state"] == PAGE_CURRENT
    # a page that cites nothing rests on nothing, whatever its record says
    assert page_freshness([], record_matches_text=False) == {
        "state": PAGE_CURRENT,
        "record_matches_text": False,
        "pending_memory_ids": [],
        "frontier": {"cited_memories": 0, "max_memory_id": None},
    }


def test_a_record_of_another_text_fails_the_page_before_pending():
    sources = [{"memory_id": 3}, {"memory_id": 5, "stale": True}]
    assert page_freshness(sources, record_matches_text=False) == {
        "state": PAGE_FAILED,
        "record_matches_text": False,
        "pending_memory_ids": [5],
        "frontier": {"cited_memories": 2, "max_memory_id": 5},
    }


def test_the_verdict_survives_the_cut_of_the_trace():
    sources = [{"memory_id": i} for i in range(40)] + [{"memory_id": 99, "stale": True}]
    resp = {"content": "x" * 200, "sources": sources}
    resp["freshness"] = page_freshness(sources, record_matches_text=True)
    fit_sources(resp, 600)
    assert resp["sources_truncated"] is True
    assert 99 not in [ref["memory_id"] for ref in resp["sources"]]
    assert resp["freshness"]["state"] == PAGE_PENDING
    assert resp["freshness"]["pending_memory_ids"] == [99]


def _read() -> dict:
    page = asyncio.run(wiki_read.handler({"path": _PAGE}))
    assert "sources_unavailable" not in page
    return page


def test_a_written_page_is_current_until_a_cited_memory_is_retired(
    monkeypatch, tmp_path
):
    _, _, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    assert _read()["freshness"] == {
        "state": PAGE_CURRENT,
        "record_matches_text": True,
        "pending_memory_ids": [],
        "frontier": {"cited_memories": 2, "max_memory_id": max(cited)},
    }
    monkeypatch.setattr(forget, "_store", None)
    # ingest_document protects its summaries, so the test forces the forget
    out = asyncio.run(
        forget.handler({"memory_id": cited[1], "force": True, "soft": True})
    )
    assert out["cited_by_pages"] == [_PAGE]
    freshness = _read()["freshness"]
    assert freshness["state"] == PAGE_PENDING
    assert freshness["pending_memory_ids"] == [cited[1]]


def test_citations_accumulate_across_writes_of_the_same_page(monkeypatch, tmp_path):
    """The limit the CHANGELOG documents (issue #715, review of PR #1094).

    A later write of the page with other ``memory_ids`` keeps the citations of
    the earlier one: they are recorded per page, never per write, so the page
    reads ``current`` on a memory its new text was not written from.
    """
    from mcp_server.handlers import wiki_write
    from tests_py.handlers.test_wiki_read_sources import _page_md

    _, _, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    rewritten = asyncio.run(
        wiki_write.handler(
            {
                "path": _PAGE,
                "content": _page_md("Key rotation, rewritten"),
                "mode": "replace",
                "memory_ids": [cited[0]],
            }
        )
    )
    assert rewritten["citations_written"] == 1

    page = _read()
    assert page["content"].endswith("# Key rotation, rewritten\n\nSynthesis.\n")
    assert [ref["memory_id"] for ref in page["sources"]] == cited
    assert page["freshness"]["state"] == PAGE_CURRENT
