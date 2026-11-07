"""Issue #685: recall may not silently discard an enabled search signal."""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import numpy as np
import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from mcp_server.observability import silent_failure


@pytest.fixture
def store():
    instance = SqliteMemoryStore(db_path=":memory:")
    silent_failure.reset()
    yield instance
    instance.close()
    silent_failure.reset()


def test_fts_failure_reaches_recall_caller(store):
    store.insert_memory({"content": "fixture memory", "heat": 1.0})
    store._conn.execute("DROP TABLE memories_fts")

    with pytest.raises(sqlite3.Error, match="memories_fts"):
        store.recall_memories("fixture", None)


def test_vector_failure_reaches_recall_caller(store, monkeypatch):
    assert store.has_vec, "CI installs the sqlite extra; vector coverage must run"
    error = sqlite3.OperationalError("vector index unavailable")
    monkeypatch.setattr(store, "_vec_pool_with_ties", MagicMock(side_effect=error))
    # source: sqlite_schema.py memories_vec embedding float[384].
    embedding = np.zeros(384, dtype=np.float32).tobytes()

    with pytest.raises(
        sqlite3.OperationalError, match="vector index unavailable"
    ) as caught:
        store.recall_memories("fixture", embedding)

    assert caught.value is error


def test_sqlite_dedup_index_failure_does_not_authorize_create(store):
    # This is the lower-level search used by remember, not recall's signal.
    from mcp_server.handlers.remember_helpers import try_curation

    assert store.has_vec, "CI installs the sqlite extra; vector coverage must run"
    store._conn.execute("DROP TABLE memories_vec")
    # source: sqlite_schema.py memories_vec embedding float[384].
    embedding = np.zeros(384, dtype=np.float32).tobytes()

    with pytest.raises(sqlite3.Error, match="memories_vec"):
        try_curation("fixture", embedding, False, store, MagicMock(), [], 1.0)


def test_vector_search_failure_is_not_hidden_below_curation(store):
    assert store.has_vec, "CI installs sqlite-vec; vector coverage must run"
    store._conn.execute("DROP TABLE memories_vec")
    embedding = np.zeros(384, dtype=np.float32).tobytes()
    with pytest.raises(sqlite3.Error, match="memories_vec"):
        store.search_vectors(embedding)


def test_misaligned_vector_buffer_raises(store):
    assert store.has_vec, "CI installs sqlite-vec; vector coverage must run"
    with pytest.raises(
        ValueError, match="buffer size must be a multiple of element size"
    ):
        store.search_vectors(b"\x00\x00\x00")
