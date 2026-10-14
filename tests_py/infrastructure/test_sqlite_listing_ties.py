"""SQLite listings and hook queries order exact ties newest first.

The SQLite twins of the PostgreSQL reads fixed by ADR-1106: the agent
briefing's two passes and its role-prior pass, the SessionStart banner's
``get_hot_memories``, ``get_memories_mentioning_entity`` (FTS5 and LIKE
branches), and the ``include_related`` enrichment's
``get_entities_for_memory`` and ``get_relationships_for_entity``. On cfd03db9
they ordered by one score only, so tied rows came back in rowid order. Here
rowid order is not time order (``created_at`` is shuffled against insertion)
and every read must return ``created_at DESC, id DESC``, the PostgreSQL order.

source: ADR-1106
"""

from __future__ import annotations

import pytest

from mcp_server.hooks.agent_briefing_role import _sqlite_role_rows
from mcp_server.hooks.agent_briefing_sqlite import (
    _MAX_MEMORIES,
    SqliteBriefingConnection,
    fetch_sqlite_context,
)
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore
from tests_py._tie_layouts import inserted_newest_first, newest_first, stamps

_PROJECT = "/p"
# source: test fixture -- a LIMIT below the 130 tied rows.
_LIMIT = 10


@pytest.fixture
def store(tmp_path):
    s = SqliteMemoryStore(db_path=str(tmp_path / "ties.db"))
    yield s
    s.close()


def insert_tied(store, content: str = "alpha tied row", **values) -> list[int]:
    keys = []
    for stamp in stamps():
        mid = store.insert_memory(
            {
                "content": content,
                "agent_context": "worker",
                "directory_context": _PROJECT,
                "heat": 0.5,
                "heat_base": 0.5,
                "created_at": stamp.isoformat(),
                **values,
            }
        )
        keys.append((stamp, mid))
    return newest_first(keys)


def _insert_row(store, table: str, row: dict) -> int:
    names = ", ".join(row)
    marks = ", ".join(["?"] * len(row))
    cur = store._conn.execute(
        f"INSERT INTO {table} ({names}) VALUES ({marks})",  # noqa: S608 — table and column names are this test's literals; values are bound
        tuple(row.values()),
    )
    return int(cur.lastrowid)


@pytest.mark.parametrize(
    ("values", "keywords", "source"),
    [({}, ["alpha"], "agent-prior"), ({"is_team_decision": True}, [], "team")],
)
def test_briefing_passes_keep_the_newest_ties(store, values, keywords, source):
    expected = insert_tied(store, **values)
    rows = fetch_sqlite_context(
        SqliteBriefingConnection(store), "worker", keywords, _PROJECT
    )
    assert [r["source"] for r in rows] == [source] * _MAX_MEMORIES
    assert [r["id"] for r in rows] == inserted_newest_first(expected)[:_MAX_MEMORIES]


def test_briefing_role_prior_keeps_the_newest_ties(store):
    expected = insert_tied(store)
    rows = _sqlite_role_rows(store._conn, "worker", _PROJECT, _MAX_MEMORIES)
    assert [r["id"] for r in rows] == inserted_newest_first(expected)[:_MAX_MEMORIES]


def test_hot_memories_keep_the_newest_ties(store):
    expected = insert_tied(store)
    rows = store.get_hot_memories(min_heat=0.4, limit=_LIMIT)
    assert [r["id"] for r in rows] == inserted_newest_first(expected)[:_LIMIT]


@pytest.mark.parametrize(
    ("content", "name"),
    [("zebrafish note", "zebrafish"), ("abcxyzzydef note", "xyzzy")],
    ids=["fts", "like-fallback"],
)
def test_memories_mentioning_entity_keep_the_newest_ties(store, content, name):
    expected = insert_tied(store, content)
    rows = store.get_memories_mentioning_entity(name, limit=_LIMIT)
    assert [r["id"] for r in rows] == inserted_newest_first(expected)[:_LIMIT]


def test_entities_for_memory_are_ordered_newest_first(store):
    memory = store.insert_memory({"content": "hub", "heat": 0.5})
    keys = []
    for n, stamp in enumerate(stamps()):
        row = {
            "name": f"ent{n}",
            "type": "concept",
            "heat": 1.0,
            "created_at": stamp.isoformat(),
        }
        eid = _insert_row(store, "entities", row)
        store.insert_memory_entity(memory, eid)
        keys.append((stamp, eid))
    assert [e["id"] for e in store.get_entities_for_memory(memory)] == newest_first(
        keys
    )


@pytest.mark.parametrize("direction", ["outgoing", "incoming", "both"])
def test_relationships_for_entity_keep_the_newest_ties(store, direction):
    hub = _insert_row(store, "entities", {"name": "hub", "type": "concept"})
    keys = []
    for n, stamp in enumerate(stamps()):
        other = _insert_row(store, "entities", {"name": f"leaf{n}", "type": "concept"})
        src, dst = (other, hub) if direction == "incoming" else (hub, other)
        row = {
            "source_entity_id": src,
            "target_entity_id": dst,
            "relationship_type": "co_occurs",
            "weight": 1.0,
            "created_at": stamp.isoformat(),
        }
        keys.append((stamp, _insert_row(store, "relationships", row)))
    rows = store.get_relationships_for_entity(hub, direction, limit=_LIMIT)
    assert [r["id"] for r in rows] == newest_first(keys)[:_LIMIT]
