"""PostgreSQL store listings order exact ties newest first in every layout.

``get_hot_memories`` (SQLite SessionStart banner twin, ADR-1106),
``get_memories_mentioning_entity`` (both branches), and the two reads of the
``include_related`` enrichment, ``get_entities_for_memory`` (cut by a Python
slice) and ``get_relationships_for_entity`` (all three directions), ordered by
one score with no tie-break on cfd03db9. Here 130 rows tie on that score;
the table is rewritten in three physical orders and each read must return
the same rows, ``created_at DESC, id DESC`` (ADR-1106).

Live PG (throwaway test database via conftest); skipped on SQLite, where
``test_sqlite_listing_ties.py`` covers the same methods.

source: ADR-1106
"""

from __future__ import annotations

import os

import pytest

from tests_py._tie_layouts import newest_first, same_in_every_layout, stamps
from tests_py.conftest import _TEST_DB_URL, _USE_PG

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402 — after the importorskip guard

pytestmark = pytest.mark.skipif(not _USE_PG, reason="requires isolated PostgreSQL")

# source: test fixture -- a LIMIT below the 130 tied rows.
_LIMIT = 10


@pytest.fixture
def conn():
    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as c:
        c.execute("TRUNCATE memories, entities CASCADE")
        yield c
        c.execute("TRUNCATE memories, entities CASCADE")


@pytest.fixture
def store(conn):
    from mcp_server.infrastructure.pg_store import PgMemoryStore

    s = PgMemoryStore(database_url=_TEST_DB_URL)
    yield s
    s.close()


def _insert(conn, table: str, row: dict) -> int:
    names = ", ".join(row)
    marks = ", ".join(["%s"] * len(row))
    return conn.execute(
        f"INSERT INTO {table} ({names}) VALUES ({marks}) RETURNING id",  # noqa: S608 — table and column names are this test's literals; values are bound
        tuple(row.values()),
    ).fetchone()["id"]


def insert_tied_memories(conn, content: str) -> list[int]:
    keys = []
    for stamp in stamps():
        row = {"content": content, "heat_base": 0.5, "created_at": stamp}
        keys.append((stamp, _insert(conn, "memories", row)))
    return newest_first(keys)


def insert_tied_entities(conn) -> list[int]:
    keys = []
    for n, stamp in enumerate(stamps()):
        row = {"name": f"ent{n}", "type": "concept", "heat": 1.0, "created_at": stamp}
        keys.append((stamp, _insert(conn, "entities", row)))
    return newest_first(keys)


def test_hot_memories_keep_the_newest_ties(conn, store):
    expected = insert_tied_memories(conn, "zq hot row")
    got = same_in_every_layout(
        conn,
        "memories",
        lambda: [r["id"] for r in store.get_hot_memories(min_heat=0.4, limit=_LIMIT)],
    )
    assert got == expected[:_LIMIT]


@pytest.mark.parametrize(
    ("content", "name"),
    [("zebrafish note", "zebrafish"), ("abcxyzzydef note", "xyzzy")],
    ids=["fts", "ilike-fallback"],
)
def test_memories_mentioning_entity_keep_the_newest_ties(conn, store, content, name):
    expected = insert_tied_memories(conn, content)
    got = same_in_every_layout(
        conn,
        "memories",
        lambda: [
            r["id"] for r in store.get_memories_mentioning_entity(name, limit=_LIMIT)
        ],
    )
    assert got == expected[:_LIMIT]


def test_entities_for_memory_are_ordered_newest_first(conn, store):
    memory = _insert(conn, "memories", {"content": "hub", "heat_base": 0.5})
    expected = insert_tied_entities(conn)
    for eid in expected:
        conn.execute(
            "INSERT INTO memory_entities (memory_id, entity_id) VALUES (%s, %s)",
            (memory, eid),
        )
    got = same_in_every_layout(
        conn,
        "entities",
        lambda: [e["id"] for e in store.get_entities_for_memory(memory)],
    )
    assert got == expected


@pytest.mark.parametrize("direction", ["outgoing", "incoming", "both"])
def test_relationships_for_entity_keep_the_newest_ties(conn, store, direction):
    hub = _insert(conn, "entities", {"name": "hub", "type": "concept"})
    others = [
        _insert(conn, "entities", {"name": f"leaf{n}", "type": "concept"})
        for n in range(len(stamps()))
    ]
    keys = []
    for other, stamp in zip(others, stamps(), strict=True):
        src, dst = (other, hub) if direction == "incoming" else (hub, other)
        row = {
            "source_entity_id": src,
            "target_entity_id": dst,
            "relationship_type": "co_occurs",
            "weight": 1.0,
            "created_at": stamp,
        }
        keys.append((stamp, _insert(conn, "relationships", row)))
    got = same_in_every_layout(
        conn,
        "relationships",
        lambda: [
            r["id"]
            for r in store.get_relationships_for_entity(hub, direction, limit=_LIMIT)
        ],
    )
    assert got == newest_first(keys)[:_LIMIT]
