"""wiki_extract never mines claims from a superseded memory.

Claims feed wiki_synthesize / wiki_compile, so a retracted memory mined here
would reach a wiki page. Runs the real candidate query on SQLite, in both
selection modes (backlog scan and explicit memory_id).
"""

from __future__ import annotations

import pytest

from mcp_server.handlers.wiki_extract import _memory_rows
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


@pytest.fixture
def pair():
    store = SqliteMemoryStore()
    common = {"source": "user", "domain": "wiki-extract-superseded", "heat": 0.9}
    old_id = store.insert_memory({**common, "content": "We chose Redis for caching."})
    new_id, _ = store.supersede_atomic(
        {**common, "content": "We chose Valkey for caching."}, old_id
    )
    return store, old_id, new_id


def test_backlog_scan_returns_the_head_not_the_superseded_row(pair):
    store, old_id, new_id = pair
    ids = [r["id"] for r in _memory_rows(store._conn, None, 50, True)]
    assert new_id in ids
    assert old_id not in ids


def test_explicit_memory_id_of_a_superseded_row_yields_nothing(pair):
    store, old_id, new_id = pair
    assert _memory_rows(store._conn, old_id, 50, True) == []
    assert [r["id"] for r in _memory_rows(store._conn, new_id, 50, True)] == [new_id]
