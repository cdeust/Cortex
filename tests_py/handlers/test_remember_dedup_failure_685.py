"""Issue #685: the public remember path must not insert after failed dedup."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import numpy as np
import pytest

from mcp_server.handlers import remember
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore


def test_second_vector_search_failure_stops_remember_before_insert(monkeypatch):
    store = SqliteMemoryStore(db_path=":memory:")
    try:
        assert store.has_vec, "CI installs sqlite-vec; vector coverage must run"
        original_search = store.search_vectors
        calls = []
        error = RuntimeError("dedup search unavailable")

        def search(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                raise error
            return original_search(*args, **kwargs)

        monkeypatch.setattr(store, "search_vectors", search)
        monkeypatch.setattr(remember, "_get_store", lambda: store)
        monkeypatch.setattr(remember, "_resolve_domain", lambda *_args: "fixture")
        engine = MagicMock()
        # source: sqlite_schema.py memories_vec embedding float[384].
        engine.encode.return_value = np.zeros(384, dtype=np.float32).tobytes()
        monkeypatch.setattr(remember, "get_embedding_engine", lambda: engine)
        monkeypatch.setattr(remember, "apply_modulations", lambda *_args: {"heat": 1.0})
        insert = MagicMock()
        monkeypatch.setattr(remember, "insert_and_post_process", insert)
        before = store._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]

        with pytest.raises(RuntimeError, match="dedup search unavailable") as caught:
            asyncio.run(
                remember.handler(
                    {
                        "content": "A deliberate fixture fact for dedup failure",
                        "write_class": "deliberate",
                        "is_global": True,
                    }
                )
            )

        assert caught.value is error
        assert len(calls) == 2
        assert calls[0]["heads_only"] is True
        assert "heads_only" not in calls[1]
        insert.assert_not_called()
        assert (
            store._conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == before
        )
    finally:
        store.close()
