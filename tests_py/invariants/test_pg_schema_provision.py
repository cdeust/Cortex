"""Hermetic, mocked unit tests for tests_py/_pg_schema_provision.py's
reachability and database-existence helpers — the issue #312 fix
(reachable-but-unprovisioned databases get PROVISIONED, not skipped).

Mirrors `tests_py/invariants/test_pg_throwaway_db.py`'s mocking strategy: a
fake `psycopg` module is injected via `mock.patch.dict(sys.modules, ...)`
so no real network/DB call is made, and `pytest.exit` is patched on the
real `pytest` object so the fail-loud branches can be asserted without
actually aborting this test session (same technique as
`tests_py/invariants/test_real_data_root_guard.py` /
`test_guard_against_populated_db.py`).

Split from the schema-provisioning + orchestration tests
(`test_pg_schema_provision_ready.py`) to stay under coding-standards.md
§4.1's 300-line cap — the same boundary `_pg_safety_guards.py`'s own test
suite already uses (`test_guard_against_populated_db.py` +
`test_guard_blocks_populated_db.py` + the structural file), splitting by
concern rather than by an arbitrary line count.

These tests pin the CONTRACT (exact SQL text, exact call arguments, which
branch calls `pytest.exit` vs which returns quietly) at full mutation-
testing speed. The end-to-end CLAIM — a bare throwaway database really
ends up with `memories`/`entities`/`memory_entities`/`relationships`
after `ensure_pg_ready` — is proven separately, against a REAL local
PostgreSQL, in `test_pg_schema_provision_live.py` (Move 5: do not mock
what only a real backend can confirm).
"""

from __future__ import annotations

import sys
import types
import unittest.mock as mock

from tests_py import _pg_schema_provision as provision


def _fake_psycopg(
    connect_side_effect: Exception | list[object] | None = None,
    connect_return: object | None = None,
) -> types.ModuleType:
    fake = types.ModuleType("psycopg")
    fake.errors = types.SimpleNamespace(
        DuplicateDatabase=type("DuplicateDatabase", (Exception,), {}),
    )
    if connect_side_effect is not None:
        fake.connect = mock.Mock(side_effect=connect_side_effect)
    else:
        fake.connect = mock.Mock(return_value=connect_return)
    return fake


def _conn_cm(exists_row: tuple | None) -> mock.MagicMock:
    """A `with psycopg.connect(...) as conn:` fake whose
    `conn.execute("SELECT 1 FROM pg_database ...").fetchone()` returns
    `exists_row`."""
    conn = mock.MagicMock()
    conn.__enter__ = mock.Mock(return_value=conn)
    conn.__exit__ = mock.Mock(return_value=False)
    conn.execute.return_value.fetchone.return_value = exists_row
    return conn


class TestCanConnect:
    def test_returns_true_when_connect_succeeds(self) -> None:
        conn = mock.MagicMock()
        conn.__enter__ = mock.Mock(return_value=conn)
        conn.__exit__ = mock.Mock(return_value=False)
        fake_pg = _fake_psycopg(connect_return=conn)
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            assert provision._can_connect("postgresql://x/db") is True

    def test_returns_false_when_connect_raises(self) -> None:
        fake_pg = _fake_psycopg(connect_side_effect=Exception("refused"))
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            assert provision._can_connect("postgresql://x/db") is False

    def test_returns_false_when_psycopg_is_not_installed(self) -> None:
        with mock.patch.dict(sys.modules, {"psycopg": None}):
            assert provision._can_connect("postgresql://x/db") is False

    def test_connects_with_exact_reachability_args(self) -> None:
        """Pins `autocommit=True, connect_timeout=3` — a mutant weakening
        either (e.g. `connect_timeout=0`) would pass every other test in
        this class undetected."""
        conn = mock.MagicMock()
        conn.__enter__ = mock.Mock(return_value=conn)
        conn.__exit__ = mock.Mock(return_value=False)
        fake_pg = _fake_psycopg(connect_return=conn)
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            provision._can_connect("postgresql://x/db")
        fake_pg.connect.assert_called_once_with(
            "postgresql://x/db", autocommit=True, connect_timeout=3
        )


class TestDatabaseName:
    def test_extracts_name_after_rightmost_slash(self) -> None:
        assert (
            provision._database_name("postgresql://host:5432/cortex_test")
            == "cortex_test"
        )

    def test_drops_query_string_first(self) -> None:
        assert (
            provision._database_name("postgresql://host/cortex_test?sslmode=require")
            == "cortex_test"
        )

    def test_query_string_containing_its_own_slash_does_not_confuse_it(self) -> None:
        """A query string with its own "/" (e.g. a file-path option) must
        not be mistaken for the database-name separator — the "?" split
        has to happen BEFORE the rightmost-"/" split, not after (same
        property `_pg_throwaway_db.maintenance_url` pins for its own
        parsing)."""
        assert (
            provision._database_name("postgresql://host/cortex_test?options=/tmp/foo")
            == "cortex_test"
        )


class TestCreateDatabase:
    def test_returns_early_when_database_already_exists(self) -> None:
        conn = _conn_cm(exists_row=(1,))
        fake_pg = _fake_psycopg(connect_return=conn)
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            provision._create_database("postgresql://host/cortex_test")
        calls = [c.args[0] for c in conn.execute.call_args_list]
        assert not any(c.startswith("CREATE DATABASE") for c in calls)

    def test_creates_database_when_missing(self) -> None:
        conn = _conn_cm(exists_row=None)
        fake_pg = _fake_psycopg(connect_return=conn)
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            provision._create_database("postgresql://host/cortex_test")
        conn.execute.assert_called_with('CREATE DATABASE "cortex_test"')

    def test_connects_to_the_maintenance_url_not_the_target(self) -> None:
        conn = _conn_cm(exists_row=(1,))
        fake_pg = _fake_psycopg(connect_return=conn)
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            provision._create_database("postgresql://host/cortex_test")
        fake_pg.connect.assert_called_once_with(
            "postgresql://host/postgres", autocommit=True, connect_timeout=3
        )

    def test_existence_check_is_parameter_bound(self) -> None:
        conn = _conn_cm(exists_row=(1,))
        fake_pg = _fake_psycopg(connect_return=conn)
        with mock.patch.dict(sys.modules, {"psycopg": fake_pg}):
            provision._create_database("postgresql://host/cortex_test")
        query, params = conn.execute.call_args_list[0].args
        assert query == "SELECT 1 FROM pg_database WHERE datname = %s"
        assert params == ("cortex_test",)

    def test_duplicate_database_race_is_swallowed_not_escalated(self) -> None:
        """A concurrent process creating the same database between our
        SELECT and our CREATE DATABASE must be treated as success, not
        escalated via `pytest.exit` — the database exists either way."""
        conn = _conn_cm(exists_row=None)
        fake_pg = _fake_psycopg(connect_return=conn)
        conn.execute.side_effect = [
            mock.MagicMock(fetchone=lambda: None),  # SELECT: not found yet
            fake_pg.errors.DuplicateDatabase("already exists"),  # CREATE: raced
        ]
        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(provision.pytest, "exit") as mock_exit,
        ):
            provision._create_database("postgresql://host/cortex_test")
        mock_exit.assert_not_called()

    def test_other_create_failure_calls_pytest_exit_with_actionable_message(
        self,
    ) -> None:
        conn = _conn_cm(exists_row=None)
        fake_pg = _fake_psycopg(connect_return=conn)
        conn.execute.side_effect = [
            mock.MagicMock(fetchone=lambda: None),
            Exception("permission denied to create database"),
        ]
        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(provision.pytest, "exit") as mock_exit,
        ):
            provision._create_database("postgresql://host/cortex_test")
        mock_exit.assert_called_once()
        message, kwargs = mock_exit.call_args
        assert kwargs.get("returncode") == 2
        assert "cortex_test" in message[0]
        assert "postgresql://host/postgres" in message[0]
        assert "issue #312" in message[0]
        assert "CREATEDB" in message[0]
        assert "permission denied to create database" in message[0]
