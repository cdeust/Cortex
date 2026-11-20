"""I6-D7/INC6.8: wiki_write's page-sync + memory-citation write-path.

Mirrors ``test_wiki_read_citations.py``'s fidelity-fake approach: fakes
reproduce the exact DB-level contracts of the collaborators they
replace, so handler-level assertions are meaningful without a live PG.

- ``page_row_from_md`` + ``upsert_page`` — sync the just-written file
  into wiki.pages so a citation has a page_id to attach to.
- ``insert_citation`` — unqualified ``ON CONFLICT DO NOTHING`` dedups
  on EITHER (page_id, session_id) [session_id <> ''] OR (page_id,
  memory_id) [memory_id IS NOT NULL] — two independent partial unique
  indexes (pg_schema.py). The fake below reproduces both.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mcp_server.handlers import wiki_write
from mcp_server.observability import silent_failure
from tests_py.handlers._wiki_write_citation_fakes import (
    _FakeCitations,
    _FakeConn,
    _FakePages,
    _FakeStore,
    _Violations,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def tmp_wiki(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(wiki_write, "WIKI_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _clean_silent_failure():
    """The failure registry is process-wide: leave it as each test found it."""
    silent_failure.reset()
    yield
    silent_failure.reset()


@pytest.fixture
def wired_pg(monkeypatch):
    violations = _Violations()
    store = _FakeStore(_FakeConn(), _FakeConn(), violations)
    pages = _FakePages(violations)
    citations = _FakeCitations(violations)
    pages.request_conn = citations.request_conn = store.request_conn

    monkeypatch.setattr(wiki_write, "get_shared_store", lambda *a, **kw: store)
    monkeypatch.setattr(wiki_write, "upsert_page", pages.upsert)
    monkeypatch.setattr(wiki_write, "clear_page_retractions", pages.clear_retractions)
    monkeypatch.setattr(
        wiki_write, "page_retractions_frontier", pages.retraction_frontier
    )
    monkeypatch.setattr(wiki_write, "insert_citation", citations.insert)
    monkeypatch.setattr(
        wiki_write, "delete_page_memory_citations", citations.delete_memory_rows
    )
    store.memories = {10: {"source": "session"}, 20: {"source": None}}
    yield pages, citations
    assert violations == [], violations


# ── 1. Job executed with memory_ids → N citation rows carrying memory_id ──


def test_write_with_memory_ids_records_one_citation_per_id(tmp_wiki, wired_pg) -> None:
    pages, citations = wired_pg

    result = _run(
        wiki_write.handler(
            {
                "path": "reference/a.md",
                "content": "# A\n\nBody.",
                "memory_ids": [10, 20, 30],
            }
        )
    )

    assert "error" not in result
    assert result["citations_written"] == 3
    page_id = pages.by_path["reference/a.md"]
    assert {r[3] for r in citations.rows} == {10, 20, 30}
    assert all(r[0] == page_id for r in citations.rows)


# ── 2. A full write that names its sources replaces the page's citations ──


def test_a_replace_cites_the_memories_of_the_last_write_only(
    tmp_wiki, wired_pg
) -> None:
    """issue #715 criterion 1: a corrected source leaves the rewritten page."""
    _, citations = wired_pg
    args = {"path": "reference/a.md", "content": "# A\n\nBody.", "mode": "create"}
    _run(wiki_write.handler({**args, "memory_ids": [10, 20]}))
    citations.rows.append((1, "s-read", "", None))  # a session read of the page
    result = _run(
        wiki_write.handler({**args, "mode": "replace", "memory_ids": [20, 30]})
    )

    assert "error" not in result
    assert result["citations_written"] == 2
    assert sorted(r[3] for r in citations.rows if r[3] is not None) == [20, 30]
    assert (1, "s-read", "", None) in citations.rows


def test_an_append_or_a_write_naming_no_source_keeps_the_citations(
    tmp_wiki, wired_pg
) -> None:
    _, citations = wired_pg
    args = {"path": "reference/a.md", "content": "# A\n\nBody.", "mode": "create"}
    _run(wiki_write.handler({**args, "memory_ids": [10]}))
    _run(wiki_write.handler({**args, "mode": "append", "memory_ids": [20]}))
    _run(wiki_write.handler({**args, "mode": "replace", "content": "# A\n\nNew."}))
    assert sorted(r[3] for r in citations.rows) == [10, 20]


def test_a_full_write_clears_the_page_retractions_an_append_keeps_them(
    tmp_wiki, wired_pg
) -> None:
    """issue #715 criterion 1: the refresh a hard forget left the page waiting for."""
    pages, _ = wired_pg
    for mode in ("create", "append", "replace"):
        args = {"path": "reference/a.md", "content": "# A\n\nBody.", "mode": mode}
        assert "error" not in _run(wiki_write.handler(args))
    page_id = pages.by_path["reference/a.md"]
    assert pages.cleared == [page_id, page_id]


def test_a_full_write_that_leaves_the_page_as_it_was_keeps_its_retractions(
    tmp_wiki, wired_pg
) -> None:
    """Review of PR #1109, note 2: the text still says what the erased memory said."""
    pages, _ = wired_pg
    args = {"path": "reference/a.md", "content": "# A\n\nBody.", "mode": "create"}
    assert "error" not in _run(wiki_write.handler(args))
    assert "error" not in _run(wiki_write.handler({**args, "mode": "replace"}))
    assert pages.cleared == [pages.by_path["reference/a.md"]]


def test_a_full_write_clears_only_up_to_the_frontier_read_before_its_file(
    tmp_wiki, wired_pg, monkeypatch
) -> None:
    """Codex review of PR #1109: a forget during the write keeps its retraction."""
    pages, _ = wired_pg
    pages.last_retraction = 7
    real_write = wiki_write.write_page

    def write_then_forget(*args, **kwargs):
        result = real_write(*args, **kwargs)
        pages.last_retraction = 8  # a hard forget ran after the file was written
        return result

    monkeypatch.setattr(wiki_write, "write_page", write_then_forget)
    args = {"path": "reference/a.md", "content": "# A\n\nBody.", "mode": "create"}
    assert "error" not in _run(wiki_write.handler(args))
    assert pages.cleared_up_to == [7]


def test_an_unread_frontier_clears_no_retraction(
    tmp_wiki, wired_pg, monkeypatch
) -> None:
    """The page stays pending rather than read current on an unknown frontier."""
    pages, _ = wired_pg

    def unreachable(conn):
        raise RuntimeError("PG unreachable")

    monkeypatch.setattr(wiki_write, "page_retractions_frontier", unreachable)
    args = {"path": "reference/a.md", "content": "# A\n\nBody.", "mode": "create"}
    out = _run(wiki_write.handler(args))
    assert "error" not in out and "citations_interrupted" not in out
    assert pages.cleared == []
    noted = silent_failure.status()["wiki_write.retraction_frontier"]
    assert noted == {"last_error": "RuntimeError: PG unreachable", "count": 1}


# ── 3. An authoring citation carries session_id '' (schema default) and is
#      keyed on memory_id only, whatever the window session ──────────────


def test_an_authoring_citation_carries_no_session(tmp_wiki, wired_pg) -> None:
    """Codex review of PR #1110: the session key belongs to wiki_read's rows."""
    pages, citations = wired_pg

    result = _run(
        wiki_write.handler(
            {"path": "reference/a.md", "content": "# A\n\nBody.", "memory_ids": [10]}
        )
    )

    assert "error" not in result
    assert result["citations_written"] == 1
    assert citations.rows[0][1] == ""  # session_id column default, not None


# ── 4. No memory_ids passed → page still synced, 0 citations, no error ─────


def test_no_memory_ids_writes_page_zero_citations(tmp_wiki, wired_pg) -> None:
    pages, citations = wired_pg

    result = _run(wiki_write.handler({"path": "reference/a.md", "content": "# A"}))

    assert "error" not in result
    assert result["citations_written"] == 0
    assert "citations_interrupted" not in result
    assert "reference/a.md" in pages.by_path
    assert citations.rows == []


# ── 5. Page-sync failure (PG down / upsert_page raises) → write still
#      succeeds on disk, citations degrade to 0, no exception propagates ──


def test_page_sync_failure_degrades_gracefully(tmp_wiki, wired_pg) -> None:
    pages, citations = wired_pg
    pages.raise_on_upsert = True

    result = _run(
        wiki_write.handler(
            {"path": "reference/a.md", "content": "# A", "memory_ids": [10]}
        )
    )

    assert "error" not in result
    assert result["citations_written"] == 0
    assert result["citations_interrupted"] is True
    assert citations.rows == []
    noted = silent_failure.status()["wiki_write.page_sync_citations"]
    assert noted == {"last_error": "RuntimeError: PG unreachable", "count": 1}


# ── 6. get_shared_store itself raising (PG fully unreachable) → same
#      graceful degradation ────────────────────────────────────────────────


def test_store_unreachable_degrades_gracefully(tmp_wiki, monkeypatch) -> None:
    def _boom(*a, **kw):
        raise RuntimeError("PG unreachable")

    monkeypatch.setattr(wiki_write, "get_shared_store", _boom)

    result = _run(
        wiki_write.handler(
            {"path": "reference/a.md", "content": "# A", "memory_ids": [10]}
        )
    )

    assert "error" not in result
    assert result["citations_written"] == 0
    assert result["citations_interrupted"] is True
    noted = silent_failure.status()["wiki_write.page_sync_citations"]
    assert noted == {"last_error": "RuntimeError: PG unreachable", "count": 1}
