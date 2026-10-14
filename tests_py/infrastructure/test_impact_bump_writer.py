"""``bump_memories_mentioning``: main's impact-bump UPDATE on both backends.

Main (ADR-0493) sent one psycopg-only UPDATE: ``content ILIKE '%name%'``
OR-ed across the symbols, ``NOT is_benchmark AND NOT is_stale AND
heat_base < 1.0``, no row limit, ``heat_base`` capped at 1.0 and both
timestamps refreshed. One deliberate difference: superseded rows are left
(``superseded_by_id IS NULL``), as for the file-cue boost (ADR-1086), since
``get_hot_embeddings`` ranks every row by ``heat_base`` under a LIMIT on
both backends and a bumped superseded row would take a current row's slot.
SQLite runs on a real store; PostgreSQL is checked on
the SQL it is sent, with no connection (issue #750).
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from mcp_server.infrastructure.file_memory_priming import bump_memories_mentioning
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

_BOOST = 0.15  # source: pipeline_impact_bump._IMPACT_BOOST


@pytest.fixture()
def store(tmp_path):
    s = SqliteMemoryStore(str(tmp_path / "memory.db"))
    yield s
    s.close()


def _set(store, mid: int, **values) -> None:
    cols = ", ".join(f"{k} = %s" for k in values)
    with store.acquire_interactive() as conn:
        conn.execute(
            f"UPDATE memories SET {cols} WHERE id = %s", (*values.values(), mid)
        )
        conn.commit()


def test_heat_is_capped_and_both_timestamps_refresh(store):
    mid = store.insert_memory({"content": "render loop", "heat": 0.95})
    _set(store, mid, heat_base_set_at="2000-01-01", last_accessed="2000-01-01")
    assert bump_memories_mentioning(store, ["render"], _BOOST) == 1
    row = store.get_memory(mid)
    assert row["heat_base"] == pytest.approx(1.0)
    assert not str(row["heat_base_set_at"]).startswith("2000")
    assert not str(row["last_accessed"]).startswith("2000")


def test_match_is_case_insensitive_and_wildcards_are_literal(store):
    upper = store.insert_memory({"content": "HANDLE_TOOL_CALL entry", "heat": 0.5})
    wildcard = store.insert_memory({"content": "handleXtoolXcall entry", "heat": 0.5})
    assert bump_memories_mentioning(store, ["handle_tool_call"], _BOOST) == 1
    assert store.get_memory(upper)["heat_base"] == pytest.approx(0.65)
    assert store.get_memory(wildcard)["heat_base"] == pytest.approx(0.5)


def test_superseded_stale_benchmark_and_saturated_rows_are_left(store):
    head = store.insert_memory({"content": "render v2", "heat": 0.5})
    old = store.insert_memory({"content": "render v1", "heat": 0.5})
    _set(store, old, superseded_by_id=head)
    stale = store.insert_memory({"content": "render stale", "heat": 0.5})
    store.mark_memory_stale(stale)
    bench = store.insert_memory(
        {"content": "render bench", "heat": 0.5, "is_benchmark": True}
    )
    hot = store.insert_memory({"content": "render hot", "heat": 1.0})
    assert bump_memories_mentioning(store, ["render"], _BOOST) == 1
    assert store.get_memory(head)["heat_base"] == pytest.approx(0.65)
    for mid, heat in ((old, 0.5), (stale, 0.5), (bench, 0.5), (hot, 1.0)):
        assert store.get_memory(mid)["heat_base"] == pytest.approx(heat)


def test_postgres_receives_one_unlimited_update():
    """The SQL PostgreSQL gets: one UPDATE over current ``memories`` rows,
    the three filters of main, one bound pattern per symbol, no LIMIT, one commit."""
    conn = MagicMock()
    conn.execute.return_value.rowcount = 7
    pg = MagicMock()

    @contextmanager
    def acquire():
        yield conn

    pg.acquire_interactive = acquire
    assert bump_memories_mentioning(pg, ["a_b", "c%d", "a_b"], _BOOST) == 7
    (sql, params), _ = conn.execute.call_args
    assert conn.execute.call_count == 1 and conn.commit.call_count == 1
    assert sql.startswith("UPDATE memories SET heat_base = CASE WHEN heat_base + %s")
    assert "THEN 1.0 ELSE heat_base + %s END" in sql
    assert "heat_base_set_at = NOW(), last_accessed = NOW()" in sql
    for clause in (
        "superseded_by_id IS NULL",
        "NOT COALESCE(is_benchmark, FALSE)",
        "NOT COALESCE(is_stale, FALSE)",
        "heat_base < 1.0",
    ):
        assert clause in sql
    assert "LIMIT" not in sql.upper() and "?" not in sql
    # ILIKE, not LOWER(content) LIKE: the trigram index serves only the former
    # (review of de3816f9 measured a full scan for the LOWER form).
    assert (
        re.findall(r"content ILIKE %s ESCAPE '!'", sql)
        == ["content ILIKE %s ESCAPE '!'"] * 2
    )
    assert "LOWER(" not in sql
    assert sql.count("%s") == len(params)
    assert params == (_BOOST, _BOOST, "%a!_b%", "%c!%d%")


def test_no_symbol_sends_nothing():
    pg = MagicMock()
    assert bump_memories_mentioning(pg, [], _BOOST) == 0
    pg.acquire_interactive.assert_not_called()
