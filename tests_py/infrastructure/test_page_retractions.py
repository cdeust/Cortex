"""What a hard forget leaves on the pages that cited the erased memory.

source: issue #715 (acceptance criterion 1)
"""

from __future__ import annotations

import pytest

from mcp_server.infrastructure.pg_store_wiki_pages import get_page_by_rel_path
from mcp_server.infrastructure.pg_store_wiki_retractions import (
    clear_page_retractions,
    count_page_retractions,
    page_retractions_frontier,
    record_page_retractions,
)
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from tests_py.conftest import _USE_PG  # type: ignore  # noqa: E402
from tests_py.infrastructure.test_pages_citing_memory import _two_pages_citing


@pytest.fixture(params=["sqlite", "postgresql"])
def store(request, tmp_path):
    """Both backends: the statements must run as written on SQLite and PostgreSQL."""
    if request.param == "sqlite":
        s = SqliteMemoryStore(str(tmp_path / "memory.db"))
    else:
        if not _USE_PG:
            pytest.skip("PostgreSQL test database not reachable")
        from mcp_server.infrastructure.pg_store import PgMemoryStore

        s = PgMemoryStore()
    yield s
    s.close()


def _page_ids(conn, paths: list[str]) -> list[int]:
    return [int(get_page_by_rel_path(conn, p)["id"]) for p in paths]


def test_one_row_per_citing_page_whatever_its_citation_count(store, tmp_path):
    cited, other, paths, _ = _two_pages_citing(store, tmp_path.name)
    conn = store._conn
    # the second page cites the memory twice on SQLite: still one row
    assert record_page_retractions(conn, cited) == 2
    assert [count_page_retractions(conn, i) for i in _page_ids(conn, paths)] == [1, 1]
    elsewhere = _page_ids(conn, [f"notes/{tmp_path.name}-c.md"])[0]
    assert count_page_retractions(conn, elsewhere) == 0
    assert record_page_retractions(conn, other + 1000) == 0


def test_clearing_one_page_leaves_the_others(store, tmp_path):
    cited, _, paths, _ = _two_pages_citing(store, tmp_path.name)
    conn = store._conn
    record_page_retractions(conn, cited)
    record_page_retractions(conn, cited)
    first, second = _page_ids(conn, paths)
    assert count_page_retractions(conn, first) == 2
    clear_page_retractions(conn, first, page_retractions_frontier(conn))
    assert count_page_retractions(conn, first) == 0
    assert count_page_retractions(conn, second) == 2


def test_a_clear_keeps_the_retractions_recorded_after_its_frontier(store, tmp_path):
    """Codex review of PR #1109: a forget during the write is not refreshed by it."""
    cited, _, paths, _ = _two_pages_citing(store, tmp_path.name)
    conn = store._conn
    assert page_retractions_frontier(conn) == 0
    record_page_retractions(conn, cited)
    frontier = page_retractions_frontier(conn)
    record_page_retractions(conn, cited)  # after the frontier was read
    assert page_retractions_frontier(conn) > frontier
    first, second = _page_ids(conn, paths)
    clear_page_retractions(conn, first, frontier)
    assert count_page_retractions(conn, first) == 1
    assert count_page_retractions(conn, second) == 2
