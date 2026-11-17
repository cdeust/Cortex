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
    monkeypatch.setattr(wiki_write, "insert_citation", citations.insert)
    monkeypatch.setattr(wiki_write, "current_window_session", lambda: None)
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


# ── 2. Dedup on re-run: same memory_ids again → 0 new rows ─────────────────


def test_rerun_same_memory_ids_dedups(tmp_wiki, wired_pg) -> None:
    pages, citations = wired_pg
    args = {
        "path": "reference/a.md",
        "content": "# A\n\nBody.",
        "mode": "replace",
        "memory_ids": [10, 20],
    }
    # First write is 'create'; the re-curation is a 'replace'.
    _run(wiki_write.handler({**args, "mode": "create"}))
    result = _run(wiki_write.handler(args))

    assert "error" not in result
    assert result["citations_written"] == 0
    assert len(citations.rows) == 2


# ── 3. No resolvable session → session_id '' (schema default), citations
#      still written keyed on memory_id ────────────────────────────────────


def test_no_session_still_records_citations_with_empty_session_id(
    tmp_wiki, wired_pg, monkeypatch
) -> None:
    pages, citations = wired_pg
    monkeypatch.setattr(wiki_write, "current_window_session", lambda: None)

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
