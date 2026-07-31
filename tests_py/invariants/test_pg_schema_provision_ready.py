"""Hermetic, mocked unit tests for tests_py/_pg_schema_provision.py's
schema-provisioning and top-level orchestration (issue #312).

Split from `test_pg_schema_provision.py` (which covers `_can_connect`,
`_database_name`, and `_create_database`) to stay under
coding-standards.md §4.1's 300-line cap — see that file's docstring for
the full mocking-strategy rationale shared by both.

`TestProvisionSchema` pins that `_provision_schema` reuses the exact
production migration path (`PgMemoryStore.__init__` -> `_init_schema`)
rather than a hand-copied one, and that a construction failure escalates
via `pytest.exit`, never a swallowed exception. `TestEnsurePgReady` pins
the top-level branching contract: which of the three inputs (server
reachable directly / reachable only via maintenance / not reachable at
all) leads to which of (schema provisioned silently, database created
then provisioned, `PostgresUnavailableWarning` + False) — the exact
issue #312 decision table.

`TestProvisionSchema` alone needs the real `psycopg`/`pgvector` driver
importable (`@requires_psycopg`, the same marker `tests_py/conftest.py`
already exports and 3 other test files already use): its
`mock.patch("mcp_server.infrastructure.pg_store.PgMemoryStore", ...)`
calls are STRING-targeted, so `mock.patch` must import
`mcp_server.infrastructure.pg_store` to resolve the attribute —
and that module hard-imports `psycopg`/`pgvector`/`psycopg_pool` at its
own top level (`pg_store.py`'s module docstring: "Requires:
psycopg[binary]>=3.1..."), unconditionally, regardless of which backend
a given test session selects. On a SQLite-only install (no
`[postgresql]` extra) that import raises `ModuleNotFoundError`, which
`mock.patch`'s string-target resolution surfaces as `AttributeError:
module 'mcp_server.infrastructure' has no attribute 'pg_store'` instead
of a clean skip (reproduced against a disposable venv built from
`requirements/ci-sqlite.txt`, CI run 30626458304's "Test (SQLite
backend)" job). `TestEnsurePgReady` and the standalone warning test
below need no such guard: they mock `_can_connect`/`_create_database`/
`_provision_schema` at the `provision` MODULE level, never triggering a
real import of `pg_store`.
"""

from __future__ import annotations

import unittest.mock as mock
import warnings

from tests_py import _pg_schema_provision as provision
from tests_py.conftest import requires_psycopg  # type: ignore


@requires_psycopg
class TestProvisionSchema:
    def test_constructs_store_with_the_given_url_and_closes_it(self) -> None:
        store = mock.MagicMock()
        with mock.patch(
            "mcp_server.infrastructure.pg_store.PgMemoryStore",
            return_value=store,
        ) as mock_ctor:
            provision._provision_schema("postgresql://host/cortex_test")
        mock_ctor.assert_called_once_with(database_url="postgresql://host/cortex_test")
        store.close.assert_called_once()

    def test_construction_failure_calls_pytest_exit_with_actionable_message(
        self,
    ) -> None:
        with (
            mock.patch(
                "mcp_server.infrastructure.pg_store.PgMemoryStore",
                side_effect=RuntimeError('extension "vector" is not available'),
            ),
            mock.patch.object(provision.pytest, "exit") as mock_exit,
        ):
            provision._provision_schema("postgresql://host/cortex_test")
        mock_exit.assert_called_once()
        message, kwargs = mock_exit.call_args
        assert kwargs == {"returncode": 2}
        assert message[0] == (
            "REFUSING to run: PostgreSQL database "
            "'postgresql://host/cortex_test' is reachable but applying the "
            'production schema failed: extension "vector" is not '
            "available. Fix: check the connecting role's privileges "
            "(CREATE on the database, CREATE EXTENSION for vector/pg_trgm) "
            "and PostgreSQL's own logs, then re-run (issue #312)."
        )

    def test_construction_failure_never_raises_unboundlocalerror(self) -> None:
        """Under a MOCKED (non-raising) `pytest.exit`, execution falls
        through past the `except` block — `store` was never assigned, so
        the function must `return` before reaching `store.close()`, or a
        mocked test session would crash on `UnboundLocalError` instead of
        cleanly reporting the exit call."""
        with (
            mock.patch(
                "mcp_server.infrastructure.pg_store.PgMemoryStore",
                side_effect=RuntimeError("boom"),
            ),
            mock.patch.object(provision.pytest, "exit"),
        ):
            provision._provision_schema("postgresql://host/cortex_test")  # no raise


class TestEnsurePgReady:
    def test_direct_connect_success_provisions_schema_without_creating_db(
        self,
    ) -> None:
        with (
            mock.patch.object(
                provision, "_can_connect", return_value=True
            ) as mock_can_connect,
            mock.patch.object(provision, "_create_database") as mock_create,
            mock.patch.object(provision, "_provision_schema") as mock_provision,
        ):
            result = provision.ensure_pg_ready("postgresql://host/cortex_test")
        assert result is True
        mock_can_connect.assert_called_once_with("postgresql://host/cortex_test")
        mock_create.assert_not_called()
        mock_provision.assert_called_once_with("postgresql://host/cortex_test")

    def test_genuinely_unreachable_returns_false_and_warns_once(self) -> None:
        with (
            mock.patch.object(provision, "_can_connect", return_value=False),
            mock.patch.object(provision, "_create_database") as mock_create,
            mock.patch.object(provision, "_provision_schema") as mock_provision,
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always")
            result = provision.ensure_pg_ready("postgresql://host/cortex_test")
        assert result is False
        mock_create.assert_not_called()
        mock_provision.assert_not_called()
        assert len(caught) == 1
        assert isinstance(caught[0].message, provision.PostgresUnavailableWarning)
        assert str(caught[0].message) == (
            "PostgreSQL is not reachable at 'postgresql://host/cortex_test' "
            "this session — PostgreSQL-gated tests will skip (expected on "
            "a SQLite-only install; if this environment is supposed to "
            "have PostgreSQL, that absence is the problem to fix)."
        )

    def test_unreachable_warning_uses_stacklevel_2(self) -> None:
        """stacklevel=2 attributes the warning to `ensure_pg_ready`'s
        CALLER (conftest.py's `_pg_available`), not to this module's own
        `warnings.warn` call — the whole point of surfacing it is to
        point at the session that is skipping, not at this helper.
        `pytest.warns`/`catch_warnings` do not expose the stacklevel a
        warning was raised with, so `warnings.warn` itself is mocked
        (same technique PR #319 used for the analogous check)."""
        with (
            mock.patch.object(provision, "_can_connect", return_value=False),
            mock.patch.object(provision.warnings, "warn") as mock_warn,
        ):
            provision.ensure_pg_ready("postgresql://host/cortex_test")
        mock_warn.assert_called_once()
        _args, kwargs = mock_warn.call_args
        assert kwargs.get("stacklevel") == 2

    def test_maintenance_reachable_creates_then_provisions(self) -> None:
        """Direct connect fails (target DB missing) but the maintenance
        DB IS reachable -> server is up, only the named DB is absent:
        create it, then provision, no warning."""

        def _can_connect_side_effect(url: str) -> bool:
            return url == "postgresql://host/postgres"

        with (
            mock.patch.object(
                provision, "_can_connect", side_effect=_can_connect_side_effect
            ),
            mock.patch.object(provision, "_create_database") as mock_create,
            mock.patch.object(provision, "_provision_schema") as mock_provision,
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always")
            result = provision.ensure_pg_ready("postgresql://host/cortex_test")
        assert result is True
        mock_create.assert_called_once_with("postgresql://host/cortex_test")
        mock_provision.assert_called_once_with("postgresql://host/cortex_test")
        assert caught == []

    def test_only_the_genuinely_absent_branch_ever_warns(self) -> None:
        """The direct-success and create-then-provision branches must
        never emit `PostgresUnavailableWarning` — only genuine absence
        does. A prior PR (#319) warned on a DIFFERENT condition
        (reachable-but-wrong-schema); this pins that condition no longer
        exists as a code path at all — it is provisioned, not detected."""
        with (
            mock.patch.object(provision, "_can_connect", return_value=True),
            mock.patch.object(provision, "_provision_schema"),
            warnings.catch_warnings(record=True) as caught,
        ):
            warnings.simplefilter("always")
            provision.ensure_pg_ready("postgresql://host/cortex_test")
        assert caught == []


def test_postgres_unavailable_warning_is_a_user_warning() -> None:
    assert issubclass(provision.PostgresUnavailableWarning, UserWarning)
