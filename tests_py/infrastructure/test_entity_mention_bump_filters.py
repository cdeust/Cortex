"""``get_memories_mentioning_entity``'s bump filters run before the LIMIT.

The impact bump asks for the memories it can raise: below ``max_heat``, not
stale, not benchmark (the three predicates of the pre-#750 ``UPDATE``).
Both branches (full-text first, substring fallback when it matches nothing)
and both backends apply them in the WHERE clause, so excluded rows can never
fill the limit and starve the rows the bump may raise. SQLite runs on a real
store; PostgreSQL is checked on the SQL it sends, with no connection.
"""

from __future__ import annotations

import pytest

from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

# source: any limit works; _fill inserts one excluded row more than it
_LIMIT = 3
_BUMP_FILTERS = {"max_heat": 1.0, "exclude_stale": True, "exclude_benchmark": True}
_KINDS = ("saturated", "stale", "benchmark")


@pytest.fixture()
def store(tmp_path):
    s = SqliteMemoryStore(str(tmp_path / "memory.db"))
    yield s
    s.close()


def _fill(store, word: str, kind: str) -> int:
    """``_LIMIT + 1`` hot rows of ``kind``, then the one row the bump may raise."""
    for i in range(_LIMIT + 1):
        mid = store.insert_memory(
            {
                "content": f"{word} {kind} {i}",
                "heat": 1.0 if kind == "saturated" else 0.9,
                "is_benchmark": kind == "benchmark",
            }
        )
        if kind == "stale":
            store.mark_memory_stale(mid)
    return store.insert_memory({"content": f"{word} valid", "heat": 0.3})


@pytest.mark.parametrize("kind", _KINDS)
def test_sqlite_fulltext_branch_filters_before_the_limit(store, kind):
    valid = _fill(store, "zorbaheat", kind)
    rows = store.get_memories_mentioning_entity(
        "zorbaheat", limit=_LIMIT, **_BUMP_FILTERS
    )
    assert [r["id"] for r in rows] == [valid]


@pytest.mark.parametrize("kind", _KINDS)
def test_sqlite_substring_fallback_filters_before_the_limit(store, kind):
    valid = _fill(store, "xzorbaheatx", kind)
    # "orbaheat" matches no full-text token, so only the fallback answers.
    rows = store.get_memories_mentioning_entity(
        "orbaheat", limit=_LIMIT, **_BUMP_FILTERS
    )
    assert [r["id"] for r in rows] == [valid]


def test_sqlite_without_filters_serves_saturated_and_benchmark_rows(store):
    """Other callers pass no filter and keep today's rows (hottest first)."""
    _fill(store, "zorbaheat", "benchmark")
    _fill(store, "zorbaheat", "saturated")
    rows = store.get_memories_mentioning_entity("zorbaheat", limit=_LIMIT)
    assert [r["heat_base"] for r in rows] == [1.0] * _LIMIT
    rows = store.get_memories_mentioning_entity("zorbaheat", limit=50)
    assert any(r["is_benchmark"] for r in rows)


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


def test_pg_both_branches_apply_the_bump_filters_before_the_limit(pg_store):
    store = pg_store([])
    store.get_memories_mentioning_entity("zorbaheat", limit=_LIMIT, **_BUMP_FILTERS)
    assert len(store.calls) == 2, "full-text matched nothing: fallback runs"
    for sql, params in store.calls:
        for predicate in ("NOT is_stale", "NOT is_benchmark", "heat_base < %s"):
            assert predicate in sql
            assert sql.index(predicate) < sql.index("LIMIT")
        assert params[-2:] == (1.0, _LIMIT)


def test_pg_without_filters_sends_no_bump_predicate(pg_store):
    store = pg_store([{"id": 1}])
    assert store.get_memories_mentioning_entity("zorbaheat") == [{"id": 1}]
    ((sql, params),) = store.calls
    for predicate in ("is_stale", "is_benchmark", "heat_base <"):
        assert predicate not in sql
    assert params == ("zorbaheat", 20)
