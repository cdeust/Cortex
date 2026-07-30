"""Regression guard for the anti-537k branch of
tests_py/_pg_safety_guards.py:guard_against_populated_db.

Split out of test_conftest_guard.py (issue #276/#287 boy-scout follow-up
— see test_guard_against_populated_db.py's docstring for the size-cap
rationale this split serves). This class directly tests the critical
branch the 2026-06-10 incident (537,396 production memories deleted)
demonstrated was absent: a populated, non-test-named database MUST be
blocked. Any change that weakens this branch must fail one of these
tests, making that change visible in CI before it ships.
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


class TestPopulatedDbBlocked:
    """A populated non-test-named database MUST be blocked by the guard."""

    def test_populated_db_calls_pytest_exit(self, monkeypatch: pytest.MonkeyPatch):
        """count=537396 must trigger pytest.exit(returncode=2), read from the
        exact COUNT query against the exact table the incident deleted from.

        Postcondition: pytest.exit is called exactly once with returncode=2.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        fake_pg = _fake_psycopg(row_count=537396)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guards.guard_against_populated_db("postgresql://localhost/mydb")
            mock_exit.assert_called_once()
            call_kwargs = mock_exit.call_args[1]
            assert call_kwargs.get("returncode") == 2, (
                f"pytest.exit not called with returncode=2 — got {mock_exit.call_args}"
            )
            conn = fake_pg.connect.return_value
            conn.execute.assert_called_once_with("SELECT COUNT(*) FROM memories")

    def test_exit_message_is_exact(self, monkeypatch: pytest.MonkeyPatch):
        """Exact equality (not `assertIn`): a wording tweak anywhere in this
        message is a real change a reviewer should see reflected here.

        Postcondition: pytest.exit's first positional argument matches the
        message byte-for-byte.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        row_count = 42
        url = "postgresql://localhost/mydb"
        fake_pg = _fake_psycopg(row_count=row_count)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guards.guard_against_populated_db(url)
            mock_exit.assert_called_once_with(
                f"REFUSING to run: test DB '{url}' is not named like a "
                f"test database and already holds {row_count} memories. The "
                "test suite DELETEs every table between tests — pointing it "
                "at a real store destroys it (incident 2026-06-10: 537k rows "
                "lost). Use a *_test database, or set "
                "CORTEX_TEST_ALLOW_POPULATED=1 if you really mean it.",
                returncode=2,
            )

    def test_exit_message_mentions_row_count(self, monkeypatch: pytest.MonkeyPatch):
        """The exit message must include the row count so operators can identify
        which database was pointed at.

        Postcondition: the first positional argument to pytest.exit contains the
        string representation of the count.
        """
        monkeypatch.delenv("CORTEX_TEST_ALLOW_POPULATED", raising=False)
        row_count = 42
        fake_pg = _fake_psycopg(row_count=row_count)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guards.guard_against_populated_db("postgresql://localhost/mydb")
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
        fake_pg = _fake_psycopg(row_count=1)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guards.guard_against_populated_db("postgresql://localhost/mydb")
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
        fake_pg = _fake_psycopg(row_count=0)

        with (
            mock.patch.dict(sys.modules, {"psycopg": fake_pg}),
            mock.patch.object(pytest, "exit") as mock_exit,
        ):
            guards.guard_against_populated_db("postgresql://localhost/mydb")
            mock_exit.assert_not_called()
