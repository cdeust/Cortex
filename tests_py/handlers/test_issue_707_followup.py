"""Regressions from the e7c2079 native and hosted reviews of PR #827.

source: native finding 4400997881; review 6470052457; hosted job 122836728366.
"""

from __future__ import annotations

import asyncio

from mcp_server.handlers import codebase_analyze, remember, remember_bulk
from mcp_server.core.codebase_parser import parse_file
from mcp_server.handlers.codebase_analyze_helpers import load_existing_hashes
from mcp_server.infrastructure import sqlite_sql_translate
from mcp_server.infrastructure.memory_exact import collapse_exact, insert_exact
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from tests_py.handlers.test_issue_707_exact_duplicates import store as store


def test_source_hash_refresh_preserves_replay_metadata(store, monkeypatch, tmp_path):
    monkeypatch.setattr(remember, "_store", store)
    monkeypatch.setattr(
        remember, "_resolve_domain", lambda directory, domain: "source-refresh"
    )
    first = parse_file("sample.py", "def sample():\n    return 1\n")
    second = parse_file("sample.py", "def sample():\n    return 2\n")
    memory_id, _, _ = asyncio.run(
        codebase_analyze._store_file(
            tmp_path, "sample.py", first, "source-refresh", store
        )
    )
    assert memory_id is not None and first.content_hash != second.content_hash
    store._execute(
        "UPDATE memories SET heat_base = 0.9, importance = 0.8 WHERE id = %s",
        (memory_id,),
    )
    store._conn.commit()
    before = store.get_memory(memory_id)
    replay_id, _, _ = asyncio.run(
        codebase_analyze._store_file(
            tmp_path, "sample.py", second, "source-refresh", store
        )
    )
    after = store.get_memory(memory_id)
    store._conn.rollback()
    assert replay_id == memory_id
    assert load_existing_hashes(store)["sample.py"] == (memory_id, second.content_hash)
    for key in ("heat_base", "importance", "heat_base_set_at", "content", "embedding"):
        assert after[key] == before[key]


def test_deliberate_bulk_replay_is_refused_before_curation(store, monkeypatch):
    monkeypatch.setattr(remember, "_store", store)
    args = {
        "content": "The bulk replay must preserve the original memory.",
        "write_class": "deliberate",
    }

    async def run():
        pending = remember_bulk.prepare_bulk([dict(args), dict(args)])
        first = await remember_bulk.store_prepared(pending[0])
        before = store.get_memory(first["memory_id"])
        second = await remember_bulk.store_prepared(pending[1])
        return first, before, second

    first, before, replay = asyncio.run(run())
    assert first["stored"]
    assert replay == {
        "stored": False,
        "action": "rejected",
        "reason": "exact_duplicate",
        "memory_id": first["memory_id"],
    }
    after = store.get_memory(first["memory_id"])
    assert after == before


def test_distinct_scopes_do_not_request_a_write_lock(store, monkeypatch):
    for domain in ("one-scope", "another-scope"):
        store.insert_memory(
            {"content": "identical text across scopes", "domain": domain}
        )
    if isinstance(store, SqliteMemoryStore):
        original = type(store._conn).execute

        def guarded(conn, query, *args, **kwargs):
            assert "BEGIN IMMEDIATE" not in query.upper()
            return original(conn, query, *args, **kwargs)

        monkeypatch.setattr(type(store._conn), "execute", guarded)
        result = collapse_exact(store)
    else:
        with store._create_connection() as writer, writer.transaction():
            writer.execute("LOCK TABLE memories IN ROW EXCLUSIVE MODE")
            result = collapse_exact(store)
    assert result == {"superseded_total": 0}


def test_collapse_works_without_sqlite_returning(tmp_path, monkeypatch):
    backend = SqliteMemoryStore(str(tmp_path / "older-sqlite.db"))
    try:
        monkeypatch.setattr(sqlite_sql_translate, "_SUPPORTS_RETURNING", False)
        ids = [
            backend.insert_memory({"content": "portable collapse"}) for _ in range(2)
        ]
        assert collapse_exact(backend) == {"superseded_total": 1}
        assert backend.get_memory(ids[1])["superseded_by_id"] == ids[0]
    finally:
        backend.close()


def test_hard_forget_erases_retained_twins_without_other_scopes(store):
    first = store.insert_memory({"content": "erase retained twin", "domain": "private"})
    twin = store.insert_memory({"content": "erase retained twin", "domain": "private"})
    independent = store.insert_memory(
        {"content": "erase retained twin", "domain": "other"}
    )
    assert collapse_exact(store) == {"superseded_total": 1}
    report = store.erase_memory(first)
    assert report.deleted
    assert store.get_memory(first) is None
    assert store.get_memory(twin) is None
    assert store.get_memory(independent) is not None


def test_stale_and_benchmark_writes_keep_separate_identity(store):
    stale = store.insert_memory({"content": "stale content"})
    store._execute("UPDATE memories SET is_stale = TRUE WHERE id = %s", (stale,))
    store._conn.commit()
    assert insert_exact(store, {"content": "stale content"})[1]
    real, _ = insert_exact(store, {"content": "real with benchmark"})
    benchmark, inserted = insert_exact(
        store, {"content": "real with benchmark", "is_benchmark": True}
    )
    assert inserted and benchmark != real


def test_survivor_election_prefers_heat_over_age(store):
    older = store.insert_memory({"content": "heat election", "heat": 0.1})
    hotter = store.insert_memory({"content": "heat election", "heat": 0.9})
    assert collapse_exact(store) == {"superseded_total": 1}
    assert store.get_memory(older)["superseded_by_id"] == hotter


def test_pg_collapse_allows_an_unrelated_writer(store):
    if isinstance(store, SqliteMemoryStore):
        return
    for _ in range(2):
        store.insert_memory({"content": "group collapse while writing"})
    with store._create_connection() as writer, writer.transaction():
        writer.execute("INSERT INTO memories (content) VALUES ('unrelated writer')")
        assert collapse_exact(store) == {"superseded_total": 1}
