"""wiki_read says whether a memory-derived page still matches its sources.

source: issue #715 (slice 2, criterion 3; criterion 1 for the retractions)
"""

from __future__ import annotations

import asyncio

from mcp_server.core.wiki_page_freshness import (
    PAGE_CURRENT,
    PAGE_FAILED,
    PAGE_PENDING,
    page_freshness,
)
from mcp_server.handlers import forget, wiki_read, wiki_write
from mcp_server.handlers.wiki_read_sources import fit_sources
from tests_py.handlers.test_wiki_read_sources import (
    _page_md,
    _two_documents_and_a_page,
)

_PAGE = "notes/key-rotation.md"


def test_each_changed_citation_makes_the_page_pending_in_citation_order():
    sources = [
        {"memory_id": 4},
        {"memory_id": 9, "stale": True},
        {"memory_id": 2, "superseded_by_id": 11},
        {"memory_id": 7, "missing": True},
    ]
    assert page_freshness(sources, record_matches_text=True, retracted_sources=0) == {
        "state": PAGE_PENDING,
        "record_matches_text": True,
        "retracted_sources": 0,
        "pending_memory_ids": [9, 2, 7],
        "frontier": {"cited_memories": 4, "max_memory_id": 9},
    }


def test_live_citations_and_no_citation_are_current():
    live = [{"memory_id": 3}, {"memory_id": 5}]
    assert (
        page_freshness(live, record_matches_text=True, retracted_sources=0)["state"]
        == PAGE_CURRENT
    )
    # a page that cites nothing rests on nothing, whatever its record says
    assert page_freshness([], record_matches_text=False, retracted_sources=0) == {
        "state": PAGE_CURRENT,
        "record_matches_text": False,
        "retracted_sources": 0,
        "pending_memory_ids": [],
        "frontier": {"cited_memories": 0, "max_memory_id": None},
    }


def test_a_record_of_another_text_fails_the_page_before_pending():
    sources = [{"memory_id": 3}, {"memory_id": 5, "stale": True}]
    assert page_freshness(sources, record_matches_text=False, retracted_sources=0) == {
        "state": PAGE_FAILED,
        "record_matches_text": False,
        "retracted_sources": 0,
        "pending_memory_ids": [5],
        "frontier": {"cited_memories": 2, "max_memory_id": 5},
    }


def test_the_verdict_survives_the_cut_of_the_trace():
    sources = [{"memory_id": i} for i in range(40)] + [{"memory_id": 99, "stale": True}]
    resp = {"content": "x" * 200, "sources": sources}
    resp["freshness"] = page_freshness(
        sources, record_matches_text=True, retracted_sources=0
    )
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
        "retracted_sources": 0,
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


def _rewrite_with(content: str, memory_ids: list[int]) -> dict:
    args = {"path": _PAGE, "content": content, "mode": "replace"}
    out = asyncio.run(wiki_write.handler({**args, "memory_ids": memory_ids}))
    assert "citations_interrupted" not in out
    return out


def test_a_replace_cites_only_the_memories_its_text_was_written_from(
    monkeypatch, tmp_path
):
    """issue #715 criterion 1: citations are per full write, not per page.

    Until this change a later write kept the citations of the earlier one, so
    the page read ``current`` on memories its new text was not written from
    (the limit the CHANGELOG documented, review of PR #1094).
    """
    from tests_py.handlers.test_wiki_read_sources import _ingest

    _, _, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    third = _ingest(
        tmp_path, "egret.xml", "<h1>Egret</h1><p>drain the quorin queue</p>"
    )
    rewritten = _rewrite_with(
        _page_md("Key rotation, rewritten"), [third["summary_memory_id"]]
    )
    assert rewritten["citations_written"] == 1

    page = _read()
    assert page["content"].endswith("# Key rotation, rewritten\n\nSynthesis.\n")
    assert [ref["memory_id"] for ref in page["sources"]] == [third["summary_memory_id"]]
    assert page["freshness"]["state"] == PAGE_CURRENT


def test_a_page_rewritten_without_its_retired_source_is_current_again(
    monkeypatch, tmp_path
):
    _, _, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    monkeypatch.setattr(forget, "_store", None)
    # ingest_document protects its summaries, so the test forces the forget
    asyncio.run(forget.handler({"memory_id": cited[1], "force": True, "soft": True}))
    assert _read()["freshness"]["pending_memory_ids"] == [cited[1]]

    _rewrite_with(_page_md("Key rotation, without the retired source"), [cited[0]])
    freshness = _read()["freshness"]
    assert freshness["state"] == PAGE_CURRENT
    assert freshness["frontier"] == {"cited_memories": 1, "max_memory_id": cited[0]}


def test_a_page_read_in_the_session_keeps_every_source_of_its_rewrite(
    monkeypatch, tmp_path
):
    """Codex review of PR #1110: on PostgreSQL the session key of the read
    (``uq_wiki_citations_page_session``) refused every authoring row of the
    same session, so the rewrite left the page citing nothing."""
    _, _, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    # A window session is resolvable for the whole request. wiki_write no
    # longer reads one (raising=False): before the fix it did, and wrote it on
    # each authoring row.
    monkeypatch.setattr(wiki_read, "_resolve_session_id", lambda: "s-1110")
    monkeypatch.setattr(
        wiki_write, "current_window_session", lambda: "s-1110", raising=False
    )
    _read()  # records the session read of the page
    rewritten = _rewrite_with(_page_md("Key rotation, read then rewritten"), cited)
    assert rewritten["citations_written"] == 2
    page = _read()
    assert [ref["memory_id"] for ref in page["sources"]] == cited
    assert page["freshness"]["state"] == PAGE_CURRENT


# ── issue #715 criterion 1: a hard forget leaves a retraction ─────────────


def test_a_retraction_makes_a_page_that_cites_nothing_pending():
    assert page_freshness([], record_matches_text=True, retracted_sources=2) == {
        "state": PAGE_PENDING,
        "record_matches_text": True,
        "retracted_sources": 2,
        "pending_memory_ids": [],
        "frontier": {"cited_memories": 0, "max_memory_id": None},
    }


def test_a_retracted_page_whose_record_is_of_another_text_fails():
    out = page_freshness([], record_matches_text=False, retracted_sources=1)
    assert out["state"] == PAGE_FAILED


def _hard_forget(memory_id: int) -> dict:
    # ingest_document protects its summaries, so the test forces the forget
    out = asyncio.run(forget.handler({"memory_id": memory_id, "force": True}))
    assert out["deleted"] is True and out["method"] == "hard"
    return out


def _freshness() -> dict:
    page = asyncio.run(wiki_read.handler({"path": _PAGE}))
    assert "sources_unavailable" not in page
    return page["freshness"]


def _write(mode: str, content: str) -> dict:
    args = {"path": _PAGE, "content": content, "mode": mode}
    out = asyncio.run(wiki_write.handler(args))
    assert "citations_interrupted" not in out
    return out


def test_hard_forget_of_a_cited_memory_makes_the_page_pending(monkeypatch, tmp_path):
    _, _, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    monkeypatch.setattr(forget, "_store", None)
    assert _hard_forget(cited[0])["cited_by_pages"] == [_PAGE]
    freshness = _freshness()
    assert freshness["state"] == PAGE_PENDING
    assert freshness["retracted_sources"] == 1
    # the erased id is not kept anywhere, so it is not named
    assert freshness["pending_memory_ids"] == []
    assert freshness["frontier"] == {"cited_memories": 1, "max_memory_id": cited[1]}


def test_a_page_whose_every_source_was_erased_is_not_current(monkeypatch, tmp_path):
    _, _, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    monkeypatch.setattr(forget, "_store", None)
    for memory_id in cited:
        _hard_forget(memory_id)
    freshness = _freshness()
    assert freshness["state"] == PAGE_PENDING
    assert freshness["retracted_sources"] == 2
    assert freshness["frontier"]["cited_memories"] == 0


def test_an_append_keeps_the_page_pending(monkeypatch, tmp_path):
    _, _, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    monkeypatch.setattr(forget, "_store", None)
    _hard_forget(cited[0])
    # an append removes nothing the page said from the erased memory
    _write("append", "One more line.\n")
    assert _freshness()["state"] == PAGE_PENDING


def test_a_replace_write_is_the_refresh_that_clears_it(monkeypatch, tmp_path):
    _, _, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    monkeypatch.setattr(forget, "_store", None)
    _hard_forget(cited[0])
    _write("replace", _page_md("Key rotation, without the erased source"))
    freshness = _freshness()
    assert freshness["state"] == PAGE_CURRENT
    assert freshness["retracted_sources"] == 0
    # a later erasure is a new retraction, not the cleared one coming back
    _hard_forget(cited[1])
    assert _freshness()["retracted_sources"] == 1
