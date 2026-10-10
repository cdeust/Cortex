"""SessionStart reads of the memories table serve chain heads only.

ADR-1100: the pending-curation count and the cached-graph-path lookup are raw
SQL in the hook. They run here against a real PostgreSQL store (the hook's own
backend) and are judged by what they return, not by the text of their SQL.
"""

from __future__ import annotations

import numpy as np
import pytest

from mcp_server.core import auto_curator
from mcp_server.handlers.ingest_helpers import code_graph_tag
from mcp_server.handlers.forget import _get_store
from mcp_server.hooks import session_start as hook

_DOMAIN = "session-start-chain-heads"
_PROJECT = "/fixture/session-start-chain-heads"
# source: mcp_server/infrastructure/pg_schema.py:29 (memories.embedding vector(384))
_DIM = 384


@pytest.fixture
def pg_store():
    store = _get_store()
    if type(store).__name__ != "PgMemoryStore":
        pytest.skip("PostgreSQL backend required for the hook's raw SQL")
    yield store
    store._execute("DELETE FROM memories WHERE domain = %s", (_DOMAIN,))
    store._conn.commit()


def _record(content: str, **extra) -> dict:
    vec = np.random.default_rng(len(content)).standard_normal(_DIM).astype(np.float32)
    return {
        "content": content,
        "embedding": (vec / np.linalg.norm(vec)).tobytes(),
        "source": "user",
        "domain": _DOMAIN,
        "heat": 0.9,
        **extra,
    }


def test_pending_curation_count_is_fed_heads_only(pg_store, monkeypatch):
    old_id = pg_store.insert_memory(_record("curation sample: old value"))
    new_id, _head = pg_store.supersede_atomic(
        _record("curation sample: new value"), old_id
    )
    seen: list[int] = []
    monkeypatch.setattr(
        auto_curator,
        "count_pending_clusters",
        lambda memories, **_kw: seen.extend(m["id"] for m in memories) or 0,
    )

    hook._count_pending_curations(pg_store._conn)

    assert new_id in seen
    assert old_id not in seen


def test_cached_graph_path_is_not_served_from_a_retracted_row(pg_store):
    tag = code_graph_tag(_PROJECT)
    old_id = pg_store.insert_memory(_record("graph_path=/stale/graph.json", tags=[tag]))
    # the correction does not carry the lookup tag, so only the retracted row
    # matches it: a head-blind lookup would still serve "/stale/graph.json"
    pg_store.supersede_atomic(_record("graph_path moved, see the new run"), old_id)

    assert hook._lookup_cached_graph_path(_PROJECT) is None
