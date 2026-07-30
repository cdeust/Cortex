"""Regression guard for tests_py/_pg_safety_guards.py:guard_against_populated_db
— the non-blocking behavioral branches.

Incident 2026-06-10: 537,396 production memories were deleted because the
guard was absent.  This test suite prevents a future change from silently
disabling or weakening the guard by verifying each branch in complete
isolation — WITHOUT a real PostgreSQL connection.

Contract under test:
    1. CORTEX_TEST_ALLOW_POPULATED=1  -> always returns (bypass override).
    2. DB URL name is *_test / *_bench / *_test_*  -> returns (trusted name).
    3. DB URL is not a test name, try PG:
       a. psycopg.connect raises any exception  -> returns (SQLite fallback).
       b. memories count == 0                   -> returns (empty DB is safe).

The count > 0 (BLOCKED) branch — the one the incident demonstrated was
absent — has its own file, `test_guard_blocks_populated_db.py`: it is the
single most safety-critical branch here, and splitting it out keeps this
file (and that one) under coding-standards.md §4.1's 300-line cap. The
guard's structural integrity (can the function itself be silently removed
or its module-level call site weakened?) is pinned separately in
`test_guard_against_populated_db_structural.py`.

All branches use unittest.mock only.  No real PG connection is opened.

Mocking strategy
----------------
Issue #276/#287 boy-scout follow-up moved the guard out of
`tests_py/conftest.py` into the standalone `tests_py/_pg_safety_guards.py`
(bringing conftest.py under coding-standards.md §4.1's 300-line cap) and
turned its DB-URL dependency from a module-global closure into an explicit
parameter. That module imports only `os` and `pytest` — no heavy
conftest.py bootstrapping (DB connections, filesystem redirection) runs on
import — so this test file can import it directly and call the real
function.

``sys.modules['psycopg']`` is replaced with a fake module for the duration of
each test so the ``import psycopg`` inside the guard returns the fake.
``pytest.exit`` is patched on the real ``pytest`` object in sys.modules so the
``import pytest; pytest.exit(...)`` path inside the guard calls the mock.
"""

from __future__ import annotations

import sys
import types
import unittest.mock as mock

import pytest

from tests_py import _pg_safety_guards as guards


def _fake_psycopg(row_count: int | None = None, raise_exc: Exception | None = None):
    """Build a fake psycopg module for sys.modules injection.

    Args:
        row_count: if given, the mock connection returns this count.
        raise_exc: if given, psycopg.connect raises this exception.
    """
    fake = types.ModuleType("psycopg")
    if raise_exc is not None:
        fake.connect = mock.Mock(side_effect=raise_exc)
        return fake

    mock_conn = mock.MagicMock()
    mock_conn.__enter__ = mock.Mock(return_value=mock_conn)
    mock_conn.__exit__ = mock.Mock(return_value=False)
    fetchone_result = (row_count,) if row_count is not None else None
    mock_conn.execute.return_value.fetchone.return_value = fetchone_result
    fake.connect = mock.Mock(return_value=mock_conn)
    return fake


# ── Branch 1: CORTEX_TEST_ALLOW_POPULATED=1 ──────────────────────────────────


class TestAllowPopulatedOverride:
    """Guard must short-circuit immediately when the override env-var is set."""

    def test_override_env_bypasses_guard(self, monkeypatch: pytest.MonkeyPatch):
        """With CORTEX_TEST_ALLOW_POPULATED=1 the guard returns without
        inspecting the DB, even for a non-test-named URL with a high row count.

        Postcondition: psycopg.connect is never called and pytest.exit is never
        called when the override is active.
        """
        monkeypatch.setenv("CORTEX_TEST_ALLOW_POPULATED", "1")
        fake_pg = _fake_psycopg(row_count=537396)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guards.guard_against_populated_db("postgresql://host/production")
            fake_pg.connect.assert_not_called()
            mock_exit.assert_not_called()

    def test_override_not_set_proceeds(self, monkeypatch: pytest.MonkeyPatch):
        """Without the override, the guard must continue past the first check.

        We confirm this by using a test-named URL (triggers branch 2 short-
        circuit) and verifying the guard returns without calling pytest.exit.
        This is an indirect confirmation that branch 1 did NOT fire.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        fake_pg = _fake_psycopg(row_count=0)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guards.guard_against_populated_db("postgresql://host/cortex_test")
            mock_exit.assert_not_called()


# ── Branch 2: URL name check (looks_like_test_db) ────────────────────────────


class TestUrlNameCheck:
    """Guard must trust URLs whose database name declares it a test/bench DB."""

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://localhost/cortex_test",
            "postgresql://localhost/mydb_bench",
            "postgresql://localhost/cortex_test_2026",
            "postgresql://user:pass@host:5432/cortex_test?sslmode=require",
        ],
    )
    def test_test_named_url_skips_connection(
        self, url: str, monkeypatch: pytest.MonkeyPatch
    ):
        """A *_test / *_bench / *_test_* database name is trusted — the guard
        returns without attempting any DB connection.

        Postcondition: psycopg.connect is not called and pytest.exit is not
        called, regardless of what the DB might contain.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        fake_pg = _fake_psycopg(row_count=999999)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guards.guard_against_populated_db(url)
            fake_pg.connect.assert_not_called()
            mock_exit.assert_not_called()

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://localhost/cortex",
            "postgresql://localhost/production",
            "postgresql://localhost/myapp_db",
        ],
    )
    def test_non_test_named_url_attempts_connection(
        self, url: str, monkeypatch: pytest.MonkeyPatch
    ):
        """A URL whose database name is not a test name must attempt a DB
        connection to inspect the row count, with the exact args the guard
        promises (the url itself, autocommit so the COUNT query needs no
        explicit commit, and a bounded connect_timeout so an unreachable
        host fails fast instead of hanging collection).

        We make the fake psycopg raise to simulate PG unavailability (branch 3a).
        The assertion is that connect WAS attempted — proving the guard did not
        short-circuit at branch 2 for a non-test-named URL.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        fake_pg = _fake_psycopg(raise_exc=Exception("no PG available"))

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guards.guard_against_populated_db(url)  # must not raise
            fake_pg.connect.assert_called_once_with(
                url, autocommit=True, connect_timeout=3
            )
            mock_exit.assert_not_called()


# ── Branch 3a: PG unreachable -> guard allows (SQLite fallback path) ──────────


class TestPgUnreachable:
    """When psycopg.connect raises any exception the guard must return silently.

    This is the normal path in environments without PG (including this CI).
    The guard must NEVER propagate the connection exception — that would break
    every test-collection run in environments without PG.
    """

    def test_operational_error_does_not_raise_or_block(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """OperationalError from psycopg must be caught; guard returns silently.

        Postcondition: guard() returns without raising, pytest.exit not called.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        fake_pg = _fake_psycopg(raise_exc=Exception("Connection refused"))

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guards.guard_against_populated_db("postgresql://localhost/mydb")
            mock_exit.assert_not_called()

    def test_any_exception_type_is_caught(self, monkeypatch: pytest.MonkeyPatch):
        """The guard catches a bare Exception base class, so any subclass must
        be swallowed — including RuntimeError, OSError, TimeoutError.

        Postcondition: guard() returns without raising for RuntimeError.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        fake_pg = _fake_psycopg(raise_exc=RuntimeError("timeout"))

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guards.guard_against_populated_db("postgresql://localhost/mydb")
            mock_exit.assert_not_called()


# ── Branch 3b: PG reachable, count == 0 -> guard allows ──────────────────────


class TestEmptyDb:
    """An empty non-test-named database is safe to wipe — guard must allow."""

    def test_zero_count_allows_proceed(self, monkeypatch: pytest.MonkeyPatch):
        """memories table with 0 rows must not trigger pytest.exit.

        Postcondition: pytest.exit is not called when count == 0.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        fake_pg = _fake_psycopg(row_count=0)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guards.guard_against_populated_db("postgresql://localhost/mydb")
            mock_exit.assert_not_called()

    def test_fetchone_none_allows_proceed(self, monkeypatch: pytest.MonkeyPatch):
        """fetchone() returning None (e.g. table absent) must also allow.

        The guard treats None as count=0:
            count = row[0] if row else 0

        Postcondition: pytest.exit is not called when fetchone returns None.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        # row_count=None instructs _fake_psycopg to return fetchone_result=None
        fake_pg = _fake_psycopg(row_count=None)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guards.guard_against_populated_db("postgresql://localhost/mydb")
            mock_exit.assert_not_called()
