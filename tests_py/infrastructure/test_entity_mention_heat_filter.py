"""``get_memories_mentioning_entity(max_heat=...)`` filters before the LIMIT.

Both branches (full-text first, substring fallback when it matches nothing)
and both backends apply ``heat_base < max_heat`` in the WHERE clause, so
rows above the cap can never fill the limit and starve the rows below it
(the impact bump's starvation, review of #750). SQLite runs on a real
store; PostgreSQL is checked on the SQL it sends, with no connection.
"""

from __future__ import annotations

import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

# source: any limit works; _fill inserts one saturated row more than it
_LIMIT = 3


@pytest.fixture()
def store(tmp_path):
    s = SqliteMemoryStore(str(tmp_path / "memory.db"))
    yield s
    s.close()


def _fill(store, word: str) -> int:
    for i in range(_LIMIT + 1):
        store.insert_memory({"content": f"{word} saturated {i}", "heat": 1.0})
    return store.insert_memory({"content": f"{word} cold", "heat": 0.3})


def test_sqlite_fulltext_branch_filters_before_the_limit(store):
    cold = _fill(store, "zorbaheat")
    rows = store.get_memories_mentioning_entity("zorbaheat", limit=_LIMIT, max_heat=1.0)
    assert [r["id"] for r in rows] == [cold]


def test_sqlite_substring_fallback_filters_before_the_limit(store):
    cold = _fill(store, "xzorbaheatx")
    # "orbaheat" matches no full-text token, so only the fallback answers.
    rows = store.get_memories_mentioning_entity("orbaheat", limit=_LIMIT, max_heat=1.0)
    assert [r["id"] for r in rows] == [cold]


def test_sqlite_without_max_heat_keeps_the_hottest_first(store):
    _fill(store, "zorbaheat")
    rows = store.get_memories_mentioning_entity("zorbaheat", limit=_LIMIT)
    assert [r["heat_base"] for r in rows] == [1.0] * _LIMIT


class _RecordingPgStore:
    """``PgEntityMixin`` over a recorder: the first query returns
    ``first_rows``, every later one returns nothing."""

    def __init__(self, first_rows: list[dict]) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self._first_rows = first_rows

    def _execute(self, sql, params=()):
        self.calls.append((sql, tuple(params)))
        rows = self._first_rows if len(self.calls) == 1 else []
        return type("Cursor", (), {"fetchall": lambda _self: rows})()

    def _normalize_memory_row(self, row):
        return row


@pytest.fixture()
def pg_store():
    pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")
    from mcp_server.infrastructure.pg_store_entities import PgEntityMixin

    def make(first_rows):
        cls = type("PgRecorder", (_RecordingPgStore, PgEntityMixin), {})
        return cls(first_rows)

    return make


def test_pg_both_branches_bind_the_heat_cap_before_the_limit(pg_store):
    store = pg_store([])
    store.get_memories_mentioning_entity("zorbaheat", limit=_LIMIT, max_heat=1.0)
    assert len(store.calls) == 2, "full-text matched nothing: fallback runs"
    for sql, params in store.calls:
        assert "AND heat_base < %s" in sql
        assert sql.index("heat_base < %s") < sql.index("LIMIT")
        assert params[-2:] == (1.0, _LIMIT)


def test_pg_without_max_heat_sends_no_heat_predicate(pg_store):
    store = pg_store([{"id": 1}])
    assert store.get_memories_mentioning_entity("zorbaheat") == [{"id": 1}]
    ((sql, params),) = store.calls
    assert "heat_base <" not in sql
    assert params == ("zorbaheat", 20)
