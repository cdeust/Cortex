"""Regression guard for tests_py/conftest.py:_guard_against_populated_db.

Incident 2026-06-10: 537,396 production memories were deleted because the
guard was absent.  This test suite prevents a future change from silently
disabling or weakening the guard by verifying both branches in complete
isolation — WITHOUT a real PostgreSQL connection.

Contract under test (_guard_against_populated_db):
    1. CORTEX_TEST_ALLOW_POPULATED=1  -> always returns (bypass override).
    2. DB URL name is *_test / *_bench / *_test_*  -> returns (trusted name).
    3. DB URL is not a test name, try PG:
       a. psycopg.connect raises any exception  -> returns (SQLite fallback).
       b. memories count == 0                   -> returns (empty DB is safe).
       c. memories count > 0                    -> pytest.exit(returncode=2).

All branches use unittest.mock only.  No real PG connection is opened.

Mocking strategy
----------------
The guard body does ``import psycopg`` and ``import pytest`` as IMPORT_NAME
opcodes, which always resolve through ``sys.modules``.  The guard function is
exec'd from the raw source into a fresh namespace that carries the controlled
``_TEST_DB_URL`` — avoiding the full conftest module-level setup code that
would overwrite the URL with the real test DB URL.

``sys.modules['psycopg']`` is replaced with a fake module for the duration of
each test so the ``import psycopg`` inside the guard returns the fake.
``pytest.exit`` is patched on the real ``pytest`` object in sys.modules so the
``import pytest; pytest.exit(...)`` path inside the guard calls the mock.
"""

from __future__ import annotations

import os
import sys
import types
import unittest.mock as mock

import pytest


# ── guard loader ─────────────────────────────────────────────────────────────

_CONFTEST_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "conftest.py")
)

with open(_CONFTEST_PATH, encoding="utf-8") as _fh:
    _CONFTEST_LINES = _fh.readlines()


# Extract just the two guard-related function definitions.  We locate them by
# scanning for the ``def`` lines rather than hard-coding line numbers, so a
# shift from future edits above the functions does not break this test file.
def _find_function_block(lines: list[str], func_name: str) -> tuple[int, int]:
    """Return (start, end) 0-indexed line indices for a top-level function."""
    start = next(
        i for i, line in enumerate(lines) if line.startswith(f"def {func_name}(")
    )
    # Find the next top-level def/class/assignment (col 0) after start.
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i] and lines[i][0] not in (" ", "\t", "\n", "#", '"', "'"):
            end = i
            break
    return start, end


_looks_start, _looks_end = _find_function_block(_CONFTEST_LINES, "_looks_like_test_db")
_guard_start, _guard_end = _find_function_block(
    _CONFTEST_LINES, "_guard_against_populated_db"
)
_FUNC_SOURCE = "".join(
    _CONFTEST_LINES[_looks_start:_looks_end] + _CONFTEST_LINES[_guard_start:_guard_end]
)


def _make_guard(test_db_url: str) -> types.FunctionType:
    """Compile and return the guard function bound to the given test_db_url.

    Executes only the two function definitions (not the full conftest module
    startup code) so ``_TEST_DB_URL`` in the guard's globals is precisely the
    value we supply, independent of the actual test-session DB URL.
    """
    ns: dict = {
        "os": os,
        "pytest": pytest,
        "_TEST_DB_URL": test_db_url,
    }
    exec(compile(_FUNC_SOURCE, _CONFTEST_PATH, "exec"), ns)  # noqa: S102 — test only
    return ns["_guard_against_populated_db"]


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
        guard = _make_guard("postgresql://host/production")
        fake_pg = _fake_psycopg(row_count=537396)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guard()
            fake_pg.connect.assert_not_called()
            mock_exit.assert_not_called()

    def test_override_not_set_proceeds(self, monkeypatch: pytest.MonkeyPatch):
        """Without the override, the guard must continue past the first check.

        We confirm this by using a test-named URL (triggers branch 2 short-
        circuit) and verifying the guard returns without calling pytest.exit.
        This is an indirect confirmation that branch 1 did NOT fire.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        guard = _make_guard("postgresql://host/cortex_test")
        fake_pg = _fake_psycopg(row_count=0)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guard()
            mock_exit.assert_not_called()


# ── Branch 2: URL name check (_looks_like_test_db) ───────────────────────────


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
        guard = _make_guard(url)
        fake_pg = _fake_psycopg(row_count=999999)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guard()
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
        connection to inspect the row count.

        We make the fake psycopg raise to simulate PG unavailability (branch 3a).
        The assertion is that connect WAS attempted — proving the guard did not
        short-circuit at branch 2 for a non-test-named URL.

        Postcondition: psycopg.connect is called exactly once.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        guard = _make_guard(url)
        fake_pg = _fake_psycopg(raise_exc=Exception("no PG available"))

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guard()  # must not raise (exception is caught inside the guard)
            fake_pg.connect.assert_called_once()
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
        guard = _make_guard("postgresql://localhost/mydb")
        fake_pg = _fake_psycopg(raise_exc=Exception("Connection refused"))

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guard()
            mock_exit.assert_not_called()

    def test_any_exception_type_is_caught(self, monkeypatch: pytest.MonkeyPatch):
        """The guard catches a bare Exception base class, so any subclass must
        be swallowed — including RuntimeError, OSError, TimeoutError.

        Postcondition: guard() returns without raising for RuntimeError.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        guard = _make_guard("postgresql://localhost/mydb")
        fake_pg = _fake_psycopg(raise_exc=RuntimeError("timeout"))

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guard()
            mock_exit.assert_not_called()


# ── Branch 3b: PG reachable, count == 0 -> guard allows ──────────────────────


class TestEmptyDb:
    """An empty non-test-named database is safe to wipe — guard must allow."""

    def test_zero_count_allows_proceed(self, monkeypatch: pytest.MonkeyPatch):
        """memories table with 0 rows must not trigger pytest.exit.

        Postcondition: pytest.exit is not called when count == 0.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        guard = _make_guard("postgresql://localhost/mydb")
        fake_pg = _fake_psycopg(row_count=0)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guard()
            mock_exit.assert_not_called()

    def test_fetchone_none_allows_proceed(self, monkeypatch: pytest.MonkeyPatch):
        """fetchone() returning None (e.g. table absent) must also allow.

        The guard treats None as count=0:
            count = row[0] if row else 0

        Postcondition: pytest.exit is not called when fetchone returns None.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        guard = _make_guard("postgresql://localhost/mydb")
        # row_count=None instructs _fake_psycopg to return fetchone_result=None
        fake_pg = _fake_psycopg(row_count=None)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guard()
            mock_exit.assert_not_called()


# ── Branch 3c: PG reachable, count > 0 -> BLOCKED (the anti-537k path) ───────


class TestPopulatedDbBlocked:
    """A populated non-test-named database MUST be blocked by the guard.

    This class directly tests the critical branch that the 2026-06-10 incident
    demonstrated was absent.  Any change that weakens this branch will cause
    these tests to fail, making that change visible in CI before it ships.
    """

    def test_populated_db_calls_pytest_exit(self, monkeypatch: pytest.MonkeyPatch):
        """count=537396 must trigger pytest.exit(returncode=2).

        Postcondition: pytest.exit is called exactly once with returncode=2.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        guard = _make_guard("postgresql://localhost/mydb")
        fake_pg = _fake_psycopg(row_count=537396)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guard()
            mock_exit.assert_called_once()
            call_kwargs = mock_exit.call_args[1]
            assert call_kwargs.get("returncode") == 2, (
                f"pytest.exit not called with returncode=2 — got {mock_exit.call_args}"
            )

    def test_exit_message_mentions_row_count(self, monkeypatch: pytest.MonkeyPatch):
        """The exit message must include the row count so operators can identify
        which database was pointed at.

        Postcondition: the first positional argument to pytest.exit contains the
        string representation of the count.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        guard = _make_guard("postgresql://localhost/mydb")
        row_count = 42
        fake_pg = _fake_psycopg(row_count=row_count)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guard()
            assert mock_exit.called, "pytest.exit was not called for count=42"
            exit_message = mock_exit.call_args[0][0]
            assert str(row_count) in exit_message, (
                f"Exit message does not mention row count {row_count}: {exit_message!r}"
            )

    def test_single_row_is_enough_to_block(self, monkeypatch: pytest.MonkeyPatch):
        """Even a single pre-existing memory must block the suite.

        The guard comment states 'No threshold constant — empty is empty.'
        count=1 must be treated identically to 537,396.

        Postcondition: pytest.exit called with returncode=2 for count=1.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        guard = _make_guard("postgresql://localhost/mydb")
        fake_pg = _fake_psycopg(row_count=1)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guard()
            assert mock_exit.called, (
                "Guard did not call pytest.exit for count=1 — "
                "'empty is empty' invariant violated."
            )
            call_kwargs = mock_exit.call_args[1]
            assert call_kwargs.get("returncode") == 2

    def test_exit_not_called_for_count_zero_after_populated_check(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Boundary: count=0 must NOT trigger the block even for a non-test URL.

        This guards against an off-by-one change (count >= 0) that would
        block on every fresh empty database.

        Postcondition: pytest.exit is not called when count == 0.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        guard = _make_guard("postgresql://localhost/mydb")
        fake_pg = _fake_psycopg(row_count=0)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guard()
            mock_exit.assert_not_called()


# ── Structural guard: function present and called at module level ─────────────


class TestGuardStructuralIntegrity:
    """Static-analysis tests that verify the guard cannot be silently removed.

    These tests read the conftest source and assert structural properties —
    the function definition exists and the unconditional module-level call
    site is present.  A change that deletes the function or wraps the call
    in a conditional will fail one of these tests.
    """

    def test_function_definition_present(self):
        """_guard_against_populated_db must still be defined in conftest.py.

        Postcondition: the function definition line appears in the source.
        """
        with open(_CONFTEST_PATH, encoding="utf-8") as fh:
            source = fh.read()

        assert "def _guard_against_populated_db(" in source, (
            "conftest.py no longer defines _guard_against_populated_db — "
            "the anti-537k guard has been removed."
        )

    def test_module_level_call_present(self):
        """_guard_against_populated_db() must be called at module (col=0) level.

        The call must be unconditional — not inside an if-block or a function.
        A future refactor that moves the call inside a conditional or removes it
        entirely will cause the guard to stop running at collection time.

        Postcondition: at least one line at zero indentation contains exactly
        '_guard_against_populated_db()'.
        """
        with open(_CONFTEST_PATH, encoding="utf-8") as fh:
            lines = fh.readlines()

        module_level_calls = [
            (i + 1, line.rstrip())
            for i, line in enumerate(lines)
            if line.strip() == "_guard_against_populated_db()"
            and not line.startswith((" ", "\t"))
        ]
        assert module_level_calls, (
            "conftest.py no longer calls _guard_against_populated_db() at "
            "module level — the anti-537k guard is no longer active at "
            "test collection time. The call must exist at zero indentation."
        )

    def test_returncode_2_present_in_source(self):
        """The guard must still use returncode=2 (not 0 or 1) so CI can
        distinguish a deliberate guard-abort from a normal test failure.

        Postcondition: 'returncode=2' appears in conftest.py.
        """
        with open(_CONFTEST_PATH, encoding="utf-8") as fh:
            source = fh.read()

        assert "returncode=2" in source, (
            "conftest.py _guard_against_populated_db no longer uses "
            "returncode=2 — operators will not be able to distinguish a "
            "guard-abort from a normal test failure."
        )

    def test_incident_date_mentioned_in_guard(self):
        """The guard docstring must reference the incident date (2026-06-10)
        so future maintainers understand why the guard exists.

        Postcondition: '2026-06-10' appears in conftest.py.
        """
        with open(_CONFTEST_PATH, encoding="utf-8") as fh:
            source = fh.read()

        assert "2026-06-10" in source, (
            "The incident reference date '2026-06-10' has been removed from "
            "conftest.py — maintainers will lose context for why this guard "
            "exists."
        )
