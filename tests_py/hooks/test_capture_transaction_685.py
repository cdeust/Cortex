"""Issue #685: a failed capture merge releases unfinished SQLite writes."""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing

import pytest

from mcp_server.hooks import capture_store
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from tests_py.hooks.test_capture_worker_policy import payload


def test_failed_merge_rolls_back_before_capture_worker_reuses_store(
    monkeypatch, tmp_path
):
    path = tmp_path / "capture.sqlite3"
    store = SqliteMemoryStore(str(path))
    try:
        mid = store.insert_memory({"content": "original memory"})
        # A real merge updates memories before touching FTS. Fail that second
        # step to expose an unfinished write, rather than a mock-only error.
        store._conn.execute("DROP TABLE memories_fts")
        store._conn.commit()

        async def handler(_payload):
            store.update_memory_compression(mid, "partial merge", None, 0)
            return {"stored": True, "memory_id": mid}

        monkeypatch.setattr(
            "mcp_server.hooks.post_tool_capture._load_remember", lambda: (None, handler)
        )
        anchor = store._connection_registry.connection()
        with pytest.raises(sqlite3.Error, match="memories_fts"):
            asyncio.run(capture_store.store(payload()))

        assert store._connection_registry.connection() is anchor
        assert not anchor.in_transaction
        assert store.get_memory(mid)["content"] == "original memory"
        # An independent writer can commit immediately after the failed capture.
        with closing(sqlite3.connect(path)) as writer, writer:
            writer.execute(
                "UPDATE memories SET content = ? WHERE id = ?", ("next", mid)
            )
        assert store.get_memory(mid)["content"] == "next"
    finally:
        store.close()


def test_successful_capture_commits_real_store_write(monkeypatch, tmp_path):
    path = tmp_path / "capture-success.sqlite3"
    store = SqliteMemoryStore(str(path))
    try:

        async def handler(capture):
            mid = store.insert_memory({"content": capture["content"]})
            return {"stored": True, "memory_id": mid}

        monkeypatch.setattr(
            "mcp_server.hooks.post_tool_capture._load_remember", lambda: (None, handler)
        )
        capture = payload()
        result = asyncio.run(capture_store.store(capture))

        assert result["stored"] is True
        assert not store._connection_registry.connection().in_transaction
        with closing(sqlite3.connect(path)) as reader:
            row = reader.execute(
                "SELECT content FROM memories WHERE id = ?", (result["memory_id"],)
            ).fetchone()
        assert row[0] == capture["content"]
    finally:
        store.close()
