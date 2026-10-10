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
    entity_id = store.insert_entity({"name": "zorbalisting", "type": "concept"})
    store.insert_memory_entity(old_id, entity_id)
    store.insert_memory_entity(new_id, entity_id)
    store._test_entity = entity_id
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
    "get_all_memories_for_validation": lambda s: s.get_all_memories_for_validation(
        limit=500
    ),
    "get_memories_for_entity": lambda s: s.get_memories_for_entity(s._test_entity),
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
    "get_memories_by_tag": lambda s: s.get_memories_by_tag(_TAG, heads_only=False),
    "get_all_memories_for_validation": lambda s: s.get_all_memories_for_validation(
        limit=500, heads_only=False
    ),
    "get_memories_for_entity": lambda s: s.get_memories_for_entity(
        s._test_entity, heads_only=False
    ),
}


@pytest.mark.parametrize("reader", sorted(_MAINTENANCE_CALLS))
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


# ── The limit counts heads, not physical rows ────────────────────────────

# source: arbitrary fixture sizes; any N below the physical row count (2N) works
_CHAINS = 3
# source: arbitrary instant later than any real row, so retracted rows sort first
_FUTURE = "2999-01-01T00:00:00+00:00"


def _force_older_rows_first(store, old_ids):
    """Rank every superseded row above its replacement on every sort key a
    listing uses (heat, recency, access), so a LIMIT applied before the head
    filter would fill the whole window with retracted rows."""
    p = "%s" if _is_pg(store) else "?"
    marks = ",".join([p] * len(old_ids))
    sql = (
        f"UPDATE memories SET created_at = {p}, last_accessed = {p}, "
        f"access_count = 5 WHERE id IN ({marks})"
    )
    args = (_FUTURE, _FUTURE, *old_ids)
    if _is_pg(store):
        store._execute(sql, args)
    else:
        store._conn.execute(sql, args)
    store._conn.commit()


def _is_pg(store) -> bool:
    return not isinstance(store, SqliteMemoryStore)


@pytest.fixture
def chains(store):
    """Three superseded/head pairs; the retracted rows are the hottest."""
    base = {
        "embedding": _embedding(),
        "source": "user",
        "domain": _DOMAIN,
        "directory_context": _DIRECTORY,
        "tags": [_TAG],
    }
    old_ids, new_ids = [], []
    for i in range(_CHAINS):
        old_id = store.insert_memory(
            {**base, "content": f"zorbalisting chain {i}: old", "heat": 0.99}
        )
        new_id, _head = store.supersede_atomic(
            {**base, "content": f"zorbalisting chain {i}: new", "heat": 0.5}, old_id
        )
        old_ids.append(old_id)
        new_ids.append(new_id)
    _force_older_rows_first(store, old_ids)
    return set(old_ids), set(new_ids)


_LIMITED_READERS = {
    "get_memories_for_domain": lambda s: s.get_memories_for_domain(
        _DOMAIN, min_heat=0.0, limit=_CHAINS
    ),
    "get_hot_memories": lambda s: s.get_hot_memories(min_heat=0.0, limit=_CHAINS),
    "get_memories_mentioning_entity": lambda s: s.get_memories_mentioning_entity(
        "zorbalisting", limit=_CHAINS
    ),
    "get_recently_accessed_memories": lambda s: s.get_recently_accessed_memories(
        limit=_CHAINS, min_access_count=0
    ),
    "get_memories_by_tag": lambda s: s.get_memories_by_tag(_TAG, limit=_CHAINS),
    "get_recent_memories": lambda s: s.get_recent_memories(limit=_CHAINS),
    "get_all_memories_for_validation": lambda s: s.get_all_memories_for_validation(
        _CHAINS, after_id=0, include_stale=False
    ),
}


@pytest.mark.parametrize("reader", sorted(_LIMITED_READERS))
def test_a_listing_of_n_returns_n_heads_when_more_than_n_rows_exist(
    store, chains, reader
):
    """Six physical rows exist and the three retracted ones sort first: the
    limit has to be applied after the head filter, not before it."""
    old_ids, _new_ids = chains
    ids = _ids(_LIMITED_READERS[reader](store))
    assert len(ids) == _CHAINS
    assert not set(ids) & old_ids
