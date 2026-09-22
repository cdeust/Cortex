"""Real backend parity for file priming; source: ADR-1086"""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from mcp_server.infrastructure.file_memory_priming import prime_file_memories
from mcp_server.infrastructure.memory_store import get_shared_store


def _insert(store, content="a.py", directory="/repo", **flags):
    columns = ["content", "directory_context", "heat_base", *flags]
    values = [content, directory, 0.5, *flags.values()]
    with store.acquire_interactive() as conn:
        row = conn.execute(
            f"INSERT INTO memories ({','.join(columns)}) "
            f"VALUES ({','.join('%s' for _ in columns)}) RETURNING id",
            values,
        ).fetchone()
        conn.commit()
        return row["id"]


def _rows(store):
    with store.acquire_interactive() as conn:
        return {
            row["id"]: row for row in conn.execute("SELECT * FROM memories").fetchall()
        }


def test_priming_scope_currentness_and_one_boost_per_call():
    store = get_shared_store()
    accepted = [
        _insert(store, "a.py b.py"),
        _insert(store, directory="/repo/child"),
        _insert(store, directory="/other", is_global=True),
    ]
    rejected = [
        _insert(store, directory="/sibling"),
        _insert(store, directory=""),
        _insert(store, is_benchmark=True),
        _insert(store, is_stale=True),
        _insert(store, superseded_by_id=accepted[0]),
    ]
    assert (
        prime_file_memories(
            store, ["/repo/child/a.py", "/repo/child/b.py"], "/repo/child", 0.1
        )
        == 3
    )
    rows = _rows(store)
    assert all(rows[i]["heat_base"] == pytest.approx(0.6) for i in accepted)
    assert all(rows[i]["heat_base"] == 0.5 for i in rejected)
    assert all(rows[i]["access_count"] == 0 for i in rows)


def test_unknown_project_only_primes_global():
    store = get_shared_store()
    local = _insert(store)
    global_id = _insert(store, directory="", is_global=True)
    assert prime_file_memories(store, ["/repo/a.py"], None, 0.1) == 1
    rows = _rows(store)
    assert rows[local]["heat_base"] == 0.5
    assert rows[global_id]["heat_base"] == pytest.approx(0.6)


def test_like_metacharacters_are_literal():
    store = get_shared_store()
    matched = _insert(store, "percent%_bang!.py")
    wildcard_only = _insert(store, "percent123Xbang!.py")
    assert prime_file_memories(store, ["/repo/percent%_bang!.py"], "/repo", 0.1) == 1
    assert _rows(store)[matched]["heat_base"] == pytest.approx(0.6)
    assert _rows(store)[wildcard_only]["heat_base"] == 0.5


def test_heat_is_capped_and_timestamps_refresh_only_for_changed_rows():
    store = get_shared_store()
    memory = _insert(store)
    with store.acquire_interactive() as conn:
        conn.execute(
            "UPDATE memories SET heat_base = 0.95, last_accessed = %s, "
            "heat_base_set_at = %s",
            ("2000-01-01", "2000-01-01"),
        )
        conn.commit()
    assert prime_file_memories(store, ["/repo/a.py"], "/repo", 0.1) == 1
    before = _rows(store)[memory]
    assert before["heat_base"] == 1
    assert not str(before["last_accessed"]).startswith("2000")
    assert not str(before["heat_base_set_at"]).startswith("2000")
    assert prime_file_memories(store, ["/repo/a.py"], "/repo", 0.1) == 0
    assert _rows(store)[memory]["last_accessed"] == before["last_accessed"]


def test_failed_statement_rolls_back_without_closing_store():
    conn = MagicMock()
    conn.execute.side_effect = RuntimeError("broken statement")
    store = MagicMock()

    @contextmanager
    def acquire():
        yield conn

    store.acquire_interactive = acquire
    with pytest.raises(RuntimeError, match="broken statement"):
        prime_file_memories(store, ["/repo/a.py"], "/repo", 0.1)
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    conn.close.assert_not_called()
