"""A listing that serves memory content never returns a superseded row by default.

Root cause under test: the shared listing primitives defaulted to the physical
``memories`` table (``heads_only=False``) and every content-serving caller had
to remember to opt in. ``query_methodology`` did not, and listed the retracted
row next to its replacement. The safe read is now the default; a maintenance
caller that needs the physical chain says so with ``heads_only=False``.

Runs on SQLite always, and on PostgreSQL when the suite can reach it (the
``pg`` params skip otherwise, like every PostgreSQL-gated test in this suite).
"""

from __future__ import annotations

import numpy as np
import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from tests_py.conftest import _USE_PG  # type: ignore

_DOMAIN = "superseded-listing-defaults"
_DIRECTORY = "/fixture/superseded-listing"
_TAG = "superseded-listing-tag"
# source: mcp_server/infrastructure/pg_schema.py:29 (memories.embedding vector(384))
_DIM = 384


def _embedding() -> bytes:
    vec = np.random.default_rng(0).standard_normal(_DIM).astype(np.float32)
    return (vec / np.linalg.norm(vec)).tobytes()


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


@pytest.fixture
def pair(store):
    """(old_id, new_id): old superseded by new, same domain/directory/tag/entity."""
    common = {
        "embedding": _embedding(),
        "source": "user",
        "domain": _DOMAIN,
        "directory_context": _DIRECTORY,
        "tags": [_TAG],
        "heat": 0.9,
    }
    old_id = store.insert_memory({**common, "content": "zorbalisting fact: old value"})
    new_id, head = store.supersede_atomic(
        {**common, "content": "zorbalisting fact: new value"}, old_id
    )
    assert new_id is not None and head == old_id
    return old_id, new_id


def _ids(rows):
    return [r["id"] for r in rows]


# Every shared listing that serves memory content, called the way a new caller
# would call it: with no supersession argument at all.
_READERS = {
    "get_memories_for_domain": lambda s: s.get_memories_for_domain(
        _DOMAIN, min_heat=0.0
    ),
    "get_memories_for_directory": lambda s: s.get_memories_for_directory(
        _DIRECTORY, min_heat=0.0
    ),
    "get_hot_memories": lambda s: s.get_hot_memories(min_heat=0.0, limit=50),
    "get_memories_mentioning_entity": lambda s: s.get_memories_mentioning_entity(
        "zorbalisting"
    ),
    "get_recently_accessed_memories": lambda s: s.get_recently_accessed_memories(
        limit=50, min_access_count=0
    ),
    "get_memories_by_tag": lambda s: s.get_memories_by_tag(_TAG),
    "get_recent_memories": lambda s: s.get_recent_memories(limit=50),
}


@pytest.mark.parametrize("reader", sorted(_READERS))
def test_default_listing_excludes_the_superseded_row(store, pair, reader):
    old_id, new_id = pair
    ids = _ids(_READERS[reader](store))
    assert new_id in ids
    assert old_id not in ids


_FLAGGED = [
    "get_memories_for_domain",
    "get_memories_for_directory",
    "get_hot_memories",
    "get_memories_mentioning_entity",
    "get_recently_accessed_memories",
]

_MAINTENANCE_CALLS = {
    "get_memories_for_domain": lambda s: s.get_memories_for_domain(
        _DOMAIN, min_heat=0.0, heads_only=False
    ),
    "get_memories_for_directory": lambda s: s.get_memories_for_directory(
        _DIRECTORY, min_heat=0.0, heads_only=False
    ),
    "get_hot_memories": lambda s: s.get_hot_memories(
        min_heat=0.0, limit=50, heads_only=False
    ),
    "get_memories_mentioning_entity": lambda s: s.get_memories_mentioning_entity(
        "zorbalisting", heads_only=False
    ),
    "get_recently_accessed_memories": lambda s: s.get_recently_accessed_memories(
        limit=50, min_access_count=0, heads_only=False
    ),
}


@pytest.mark.parametrize("reader", _FLAGGED)
def test_maintenance_callers_can_still_see_the_physical_chain(store, pair, reader):
    old_id, new_id = pair
    ids = _ids(_MAINTENANCE_CALLS[reader](store))
    assert old_id in ids and new_id in ids


@pytest.mark.parametrize("reader", _FLAGGED)
def test_explicit_heads_only_matches_the_default(store, pair, reader):
    _old_id, new_id = pair
    explicit = {
        "get_memories_for_domain": lambda s: s.get_memories_for_domain(
            _DOMAIN, min_heat=0.0, heads_only=True
        ),
        "get_memories_for_directory": lambda s: s.get_memories_for_directory(
            _DIRECTORY, min_heat=0.0, heads_only=True
        ),
        "get_hot_memories": lambda s: s.get_hot_memories(
            min_heat=0.0, limit=50, heads_only=True
        ),
        "get_memories_mentioning_entity": lambda s: s.get_memories_mentioning_entity(
            "zorbalisting", heads_only=True
        ),
        "get_recently_accessed_memories": lambda s: s.get_recently_accessed_memories(
            limit=50, min_access_count=0, heads_only=True
        ),
    }[reader]
    assert sorted(_ids(explicit(store))) == sorted(_ids(_READERS[reader](store)))
    assert new_id in _ids(explicit(store))


def test_the_superseded_row_stays_readable_by_id(store, pair):
    old_id, new_id = pair
    row = store.get_memory(old_id)
    assert row is not None and row["superseded_by_id"] == new_id
