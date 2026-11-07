"""``get_memories_by_tag(source=...)`` reads only the rows one writer owns.

Issue #714: a resumable ingest counts its own receipts. Rows other writers tag
with the same provenance (a user note, a CLS abstraction inheriting common
tags) must not fill the bounded read. Runs on SQLite always, and on PostgreSQL
when the suite can reach it.
"""

from __future__ import annotations

import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from tests_py.conftest import _USE_PG  # type: ignore

_DOMAIN = "tag-read-source-filter"
_TAG = "tag-read-source-filter-tag"


@pytest.fixture(
    params=[
        "sqlite",
        pytest.param(
            "pg",
            marks=pytest.mark.skipif(
                not _USE_PG, reason="PostgreSQL not available for the pg leg"
            ),
        ),
    ]
)
def store(request):
    if request.param == "sqlite":
        yield SqliteMemoryStore()
        return
    pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    s = PgMemoryStore()
    yield s
    try:
        s._execute("DELETE FROM memories WHERE domain = %s", (_DOMAIN,))
        s._conn.commit()
    finally:
        s.close()


def _insert(store, content: str, source: str) -> int:
    return store.insert_memory(
        {"content": content, "tags": [_TAG], "source": source, "domain": _DOMAIN}
    )


def test_source_filter_skips_other_writers_before_the_limit(store):
    owned = _insert(store, "owned", "ingest_document:/a.xml")
    for index in range(3):
        _insert(store, f"foreign {index}", "cls-consolidation")
    rows = store.get_memories_by_tag(
        _TAG, limit=2, heads_only=False, source="ingest_document:/a.xml"
    )
    assert [row["id"] for row in rows] == [owned]


def test_no_source_keeps_every_writer(store):
    _insert(store, "owned", "ingest_document:/a.xml")
    _insert(store, "foreign", "user")
    assert len(store.get_memories_by_tag(_TAG, limit=10)) == 2
