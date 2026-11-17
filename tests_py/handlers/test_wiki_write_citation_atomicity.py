"""An interrupted citation write leaves no partial source frontier, and resumes.

``wiki_write(memory_ids=...)`` records the memories a page rests on in
``wiki.citations``; ``wiki_read`` derives the page's source frontier from
those rows (``core.wiki_page_freshness``). Before this slice the page row and
each citation were committed one statement at a time (PostgreSQL runs the
shared store in autocommit; SQLite kept the partial rows pending on the shared
connection for the next commit). A write interrupted after its first citation
left a frontier that named memory 3 as processed while memory 2, cited by the
same write, was never recorded. The page row and its citations now commit as
one unit: an interruption records none of them, the response says so, and the
same write run again records them all.

source: issue #715 (slice 3, acceptance criterion 2)
"""

from __future__ import annotations

import asyncio
import uuid

from mcp_server.handlers import wiki_read, wiki_write
from tests_py.handlers.test_wiki_read_sources import (
    _page_md,
    _two_documents_and_a_page,
)

_real_insert_citation = wiki_write.insert_citation


class _InterruptedError(RuntimeError):
    pass


def _interrupt_after_first_citation(monkeypatch) -> list[int | None]:
    """Let the first citation insert run, then interrupt the second.

    Returns the ids the real inserts returned, so a test can show the first
    row was written inside the unit before the interruption undid it.
    """
    real = wiki_write.insert_citation
    inserted: list[int | None] = []

    def flaky(conn, **kwargs):
        if inserted:
            raise _InterruptedError("connection lost mid-write")
        inserted.append(real(conn, **kwargs))
        return inserted[-1]

    monkeypatch.setattr(wiki_write, "insert_citation", flaky)
    return inserted


def _own_path() -> str:
    """A page path no other test used.

    Neither backend clears wiki.pages or wiki.citations between tests
    (``_TABLES_TO_CLEAN`` in tests_py/_store_cleanup.py names neither), so a
    shared path could read a row another test left as a row written here.
    """
    return f"notes/derived-{uuid.uuid4().hex}.md"


def _write(memory_ids: list[int], mode: str, rel_path: str) -> dict:
    out = asyncio.run(
        wiki_write.handler(
            {
                "path": rel_path,
                "content": _page_md("Derived"),
                "mode": mode,
                "memory_ids": memory_ids,
            }
        )
    )
    assert "error" not in out
    return out


def _first_column(sql: str, rel_path: str) -> list[int]:
    settings = wiki_write.get_memory_settings()
    store = wiki_write.get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    store._conn.commit()  # a pending partial row would be flushed here
    with store._conn.cursor() as cur:
        cur.execute(sql, (rel_path,))
        rows = cur.fetchall()
    return [int(next(iter(r.values())) if isinstance(r, dict) else r[0]) for r in rows]


def _recorded_citations(rel_path: str) -> list[int]:
    return _first_column(
        "SELECT c.memory_id FROM wiki.citations c "
        "JOIN wiki.pages p ON p.id = c.page_id "
        "WHERE p.rel_path = %s AND c.memory_id IS NOT NULL ORDER BY c.id",
        rel_path,
    )


def _recorded_pages(rel_path: str) -> list[int]:
    return _first_column("SELECT id FROM wiki.pages WHERE rel_path = %s", rel_path)


def test_an_interrupted_write_records_no_citation_and_says_so(monkeypatch, tmp_path):
    _, _, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    inserted = _interrupt_after_first_citation(monkeypatch)
    rel_path = _own_path()
    out = _write(list(reversed(cited)), mode="create", rel_path=rel_path)
    assert len(inserted) == 1 and inserted[0] is not None  # written, then undone
    assert out["citations_written"] == 0
    assert out["citations_interrupted"] is True
    assert _recorded_citations(rel_path) == []
    assert _recorded_pages(rel_path) == []  # the page row rolled back with them


def test_a_resumed_write_completes_the_frontier(monkeypatch, tmp_path):
    _, _, cited = _two_documents_and_a_page(monkeypatch, tmp_path)
    _interrupt_after_first_citation(monkeypatch)
    rel_path = _own_path()
    _write(list(reversed(cited)), mode="create", rel_path=rel_path)
    monkeypatch.setattr(wiki_write, "insert_citation", _real_insert_citation)
    resumed = _write(list(reversed(cited)), mode="replace", rel_path=rel_path)
    assert resumed["citations_written"] == 2
    assert "citations_interrupted" not in resumed
    page = asyncio.run(wiki_read.handler({"path": rel_path}))
    assert sorted(ref["memory_id"] for ref in page["sources"]) == sorted(cited)
    assert page["freshness"]["frontier"] == {
        "cited_memories": 2,
        "max_memory_id": max(cited),
    }
