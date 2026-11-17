"""The between-test cleanup clears the wiki page and citation rows.

``_TABLES_TO_CLEAN`` named neither ``wiki.pages`` nor ``wiki.citations``, so a
page a handler test wrote survived for the rest of the session and a later
test reading the same ``rel_path`` saw that row as its own. Both tables are in
the list now, on both backends and on both SQLite cleanup paths (the store's
translating connection, and the raw ``sqlite3`` fallback).

source: issue #715 (follow-up named in the comments of #1084 to #1090)
"""

from __future__ import annotations

import sqlite3

from mcp_server.handlers import wiki_write
from tests_py import _store_cleanup
from tests_py.conftest import _USE_PG_STORE, _get_raw_connection
from tests_py.handlers.test_wiki_read_sources import _two_documents_and_a_page


def _count(table: str) -> int:
    settings = wiki_write.get_memory_settings()
    store = wiki_write.get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    with store._conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS n FROM {table}")
        row = cur.fetchone()
    return int(row["n"] if isinstance(row, dict) else row[0])


def _clean_as_the_isolation_fixture_does() -> None:
    """The pre-test half of conftest's ``_test_isolation``, without the reset."""
    if not _USE_PG_STORE:
        _store_cleanup._clean_sqlite_store()
        return
    conn = _get_raw_connection()
    assert conn is not None
    try:
        _store_cleanup._clean_all_tables(conn)
    finally:
        conn.close()


def test_cleanup_removes_a_written_page_and_its_citations(monkeypatch, tmp_path):
    _two_documents_and_a_page(monkeypatch, tmp_path)
    assert _count("wiki.pages") >= 1
    assert _count("wiki.citations") == 2

    _clean_as_the_isolation_fixture_does()

    assert _count("wiki.citations") == 0
    assert _count("wiki.pages") == 0


def test_raw_sqlite_fallback_translates_the_wiki_table_names(monkeypatch, tmp_path):
    db_path = tmp_path / "fallback.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        "CREATE TABLE wiki_pages (id INTEGER PRIMARY KEY, rel_path TEXT);"
        "CREATE TABLE wiki_citations (id INTEGER PRIMARY KEY, page_id INTEGER);"
        "INSERT INTO wiki_pages (id, rel_path) VALUES (1, 'notes/a.md');"
        "INSERT INTO wiki_citations (page_id) VALUES (1);"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(_store_cleanup, "_SQLITE_DB_PATH", str(db_path))
    monkeypatch.setattr(_store_cleanup, "_clean_sqlite_via_singleton", lambda: False)

    _store_cleanup._clean_sqlite_store()

    conn = sqlite3.connect(db_path)
    try:
        counts = [
            conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("wiki_pages", "wiki_citations")
        ]
    finally:
        conn.close()
    assert counts == [0, 0]
