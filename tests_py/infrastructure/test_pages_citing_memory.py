"""The wiki pages whose citations name a memory, and what a hard forget keeps of them.

source: issue #713 (slice 4)
"""

from __future__ import annotations

import pytest

from mcp_server.infrastructure.memory_erasure import ErasureReport
from mcp_server.infrastructure.memory_exact_erasure import merge_erasure_report
from mcp_server.infrastructure.pg_store_wiki_notes import (
    insert_citation,
    list_pages_citing_memory,
)
from mcp_server.infrastructure.pg_store_wiki_pages import upsert_page
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from tests_py.conftest import _USE_PG  # type: ignore  # noqa: E402


@pytest.fixture(params=["sqlite", "postgresql"])
def store(request, tmp_path):
    """Both backends: the join must run as written on SQLite and PostgreSQL."""
    if request.param == "sqlite":
        s = SqliteMemoryStore(str(tmp_path / "memory.db"))
    else:
        if not _USE_PG:
            pytest.skip("PostgreSQL test database not reachable")
        from mcp_server.infrastructure.pg_store import PgMemoryStore

        s = PgMemoryStore()
    yield s
    s.close()


def _page(conn, rel: str) -> int:
    row = {"rel_path": rel, "slug": rel, "kind": "note", "title": rel, "body": ""}
    page_id, _ = upsert_page(conn, row)
    return page_id


def _two_pages_citing(store, run: str) -> tuple[int, int, list[str], int]:
    """``cited`` is cited by two pages (one of them twice); ``other`` by a third.

    PostgreSQL keeps one row per (page, memory) (``uq_wiki_citations_page_memory``)
    and drops the repeat; SQLite stores it. The last value is the number of rows
    that name ``cited`` on the backend at hand, counted from what was inserted.
    """
    conn = store._conn
    cited = store.insert_memory({"content": f"cited {run}", "tags": [], "domain": "d"})
    other = store.insert_memory({"content": f"other {run}", "tags": [], "domain": "d"})
    paths = [f"notes/{run}-a.md", f"notes/{run}-b.md"]
    second, first = _page(conn, paths[1]), _page(conn, paths[0])
    elsewhere = _page(conn, f"notes/{run}-c.md")
    rows = [
        insert_citation(conn, second, memory_id=cited),
        insert_citation(conn, first, memory_id=cited),
        insert_citation(conn, second, session_id=f"{run}-s", memory_id=cited),
    ]
    insert_citation(conn, elsewhere, memory_id=other)
    conn.commit()
    return cited, other, paths, sum(row is not None for row in rows)


def test_each_citing_page_comes_back_once_sorted(store, tmp_path):
    cited, other, paths, _ = _two_pages_citing(store, tmp_path.name)
    assert list_pages_citing_memory(store._conn, cited) == paths
    assert list_pages_citing_memory(store._conn, other) == [
        f"notes/{tmp_path.name}-c.md"
    ]
    assert list_pages_citing_memory(store._conn, other + 1000) == []


def test_hard_erasure_reports_the_pages_before_it_drops_their_citations(
    store, tmp_path
):
    cited, _, paths, stored = _two_pages_citing(store, tmp_path.name)
    report = store.erase_memory(cited)
    assert report.deleted is True
    assert report.cited_by_pages == paths
    assert stored >= 2  # both pages cite it on every backend
    assert report.counts["citations"] == stored
    assert list_pages_citing_memory(store._conn, cited) == []


def test_merged_reports_keep_each_citing_page_once_sorted():
    target = ErasureReport(cited_by_pages=["b.md", "c.md"])
    merge_erasure_report(target, ErasureReport(cited_by_pages=["c.md", "a.md"]))
    assert target.cited_by_pages == ["a.md", "b.md", "c.md"]
