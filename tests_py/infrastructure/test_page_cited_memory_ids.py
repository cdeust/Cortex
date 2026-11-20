"""The memories a wiki page cites, read from wiki.citations in citation order.

source: issue #713 (slice 3); issue #715 (criterion 1) for their deletion
"""

from __future__ import annotations

import pytest

from mcp_server.infrastructure.pg_store_wiki_notes import (
    delete_page_memory_citations,
    insert_citation,
    list_page_cited_memory_ids,
)
from mcp_server.infrastructure.pg_store_wiki_pages import upsert_page
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from tests_py.conftest import _USE_PG  # type: ignore  # noqa: E402


@pytest.fixture(params=["sqlite", "postgresql"])
def store(request, tmp_path):
    """Both backends: the query must run as written on SQLite and PostgreSQL."""
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


def test_ids_come_back_once_each_in_first_citation_order(store, tmp_path):
    conn = store._conn
    low = store.insert_memory({"content": "low", "tags": [], "domain": "d"})
    high = store.insert_memory({"content": "high", "tags": [], "domain": "d"})
    other = store.insert_memory({"content": "other", "tags": [], "domain": "d"})
    run = tmp_path.name
    page = _page(conn, f"notes/{run}-a.md")
    elsewhere = _page(conn, f"notes/{run}-b.md")
    insert_citation(conn, page, memory_id=high)
    insert_citation(conn, page, session_id=f"{run}-s1")  # a read: names no memory
    insert_citation(conn, page, memory_id=low)
    insert_citation(conn, page, session_id=f"{run}-s2", memory_id=high)
    insert_citation(conn, elsewhere, memory_id=other)
    conn.commit()

    assert list_page_cited_memory_ids(conn, page) == [high, low]
    assert list_page_cited_memory_ids(conn, elsewhere) == [other]


def _rows(conn, page_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM wiki.citations WHERE page_id = %s;", (page_id,)
        )
        return int(cur.fetchone()["n"])


def test_deleting_a_pages_memory_citations_keeps_its_reads_and_other_pages(
    store, tmp_path
):
    conn = store._conn
    low = store.insert_memory({"content": "low", "tags": [], "domain": "d"})
    high = store.insert_memory({"content": "high", "tags": [], "domain": "d"})
    run = tmp_path.name
    page = _page(conn, f"notes/{run}-a.md")
    elsewhere = _page(conn, f"notes/{run}-b.md")
    insert_citation(conn, page, memory_id=high)
    insert_citation(conn, page, session_id=f"{run}-s1")  # a read: names no memory
    insert_citation(conn, page, memory_id=low)
    insert_citation(conn, elsewhere, memory_id=high)
    conn.commit()

    assert delete_page_memory_citations(conn, page) == 2
    conn.commit()
    assert list_page_cited_memory_ids(conn, page) == []
    assert _rows(conn, page) == 1
    assert list_page_cited_memory_ids(conn, elsewhere) == [high]
    assert delete_page_memory_citations(conn, page) == 0
