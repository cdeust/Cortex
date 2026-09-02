"""Real-PostgreSQL integration tests for `ensure_pg_ready` (issue #312).

Move 5 (test-engineer framework): do not mock a database driver for
claims that only real backend semantics can confirm. The mocked contract
tests in `test_pg_schema_provision.py` pin exact SQL/call shape at unit
speed; these tests prove the actual end state — a bare, unprovisioned
database really ends up with the tables PG-gated tests need, a missing
database really gets created, and a role that genuinely lacks CREATEDB
really triggers the loud-failure path — against a live server, not a
fake.

Every throwaway database and role created here is scoped to a single
test and dropped in a `finally`/fixture teardown (Move 2: isolation —
these tests must not perturb `_TEST_DB_URL`, the session's own database,
or leak state into any other test).
"""

from __future__ import annotations

import os
import secrets
import warnings
from urllib.parse import urlsplit, urlunsplit

import pytest

pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")

import psycopg  # noqa: E402
from _pytest.outcomes import Exit as _PytestExit  # noqa: E402

from tests_py import _pg_throwaway_db  # noqa: E402
from tests_py._pg_schema_provision import (  # noqa: E402
    PostgresUnavailableWarning,
    ensure_pg_ready,
)
from tests_py.conftest import _TEST_DB_URL, _USE_PG  # type: ignore  # noqa: E402

pytestmark = pytest.mark.skipif(
    not _USE_PG, reason="PostgreSQL is not available for this test session"
)

_REQUIRED_TABLES = ("memories", "entities", "memory_entities", "relationships")


@pytest.fixture
def bare_throwaway_db():
    """A freshly `CREATE DATABASE`-d, zero-table database — the exact
    shape `tests_py/_pg_throwaway_db.py` produces for a local session and
    the exact repro issue #312 reports. Dropped on teardown."""
    created = _pg_throwaway_db.create_isolated_test_database(_TEST_DB_URL)
    if created is None:
        pytest.skip("could not create a throwaway database on this server")
    isolated_url, maint_url, db_name = created
    try:
        yield isolated_url
    finally:
        _pg_throwaway_db.drop_isolated_database(maint_url, db_name)


@pytest.fixture
def nonexistent_db_url():
    """A URL whose database is confirmed to NOT exist yet, on the same
    server as `_TEST_DB_URL`. Dropped on teardown if the test created it."""
    name = f"cortex_312_missing_{os.getpid()}"
    maint_url = _pg_throwaway_db.maintenance_url(_TEST_DB_URL)
    prefix = _TEST_DB_URL.rpartition("/")[0]
    url = f"{prefix}/{name}"
    with psycopg.connect(maint_url, autocommit=True, connect_timeout=3) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
    try:
        yield url
    finally:
        with psycopg.connect(maint_url, autocommit=True, connect_timeout=3) as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (name,),
            )
            conn.execute(f'DROP DATABASE IF EXISTS "{name}"')


@pytest.fixture
def lowpriv_role_url():
    """A URL, authenticated as a real PostgreSQL role with LOGIN but
    NOCREATEDB, pointed at a database name that does NOT exist yet — for
    proving the actual CREATE-DATABASE-permission-denied path (Move 5:
    real server-enforced denial, not a mocked exception). The role can
    reach the `postgres` maintenance database (PUBLIC has CONNECT there
    by default) but cannot create a new one, so `ensure_pg_ready` must
    reach `_create_database` and hit a genuine `InsufficientPrivilege`.

    Skips (does not fail) if the CURRENT connecting role itself lacks
    CREATEROLE — that is a distinct environmental precondition from
    "PostgreSQL reachable" and "target database missing", not the #312
    condition this file's other tests exercise.
    """
    maint_url = _pg_throwaway_db.maintenance_url(_TEST_DB_URL)
    role = f"cortex_312_lowpriv_{os.getpid()}"
    password = secrets.token_urlsafe(16)  # per-run; a literal scans as a secret
    try:
        with psycopg.connect(maint_url, autocommit=True, connect_timeout=3) as conn:
            conn.execute(f'DROP ROLE IF EXISTS "{role}"')
            conn.execute(
                f'CREATE ROLE "{role}" LOGIN NOCREATEDB NOSUPERUSER '
                f"PASSWORD '{password}'"
            )
    except psycopg.Error as exc:
        pytest.skip(f"cannot create a low-privilege role on this server: {exc}")

    netloc = urlsplit(maint_url).netloc.rpartition("@")[-1]  # drop any existing creds
    target_db = f"cortex_312_lowpriv_target_{os.getpid()}"
    role_url = urlunsplit(
        ("postgresql", f"{role}:{password}@{netloc}", f"/{target_db}", "", "")
    )
    try:
        yield role_url
    finally:
        with psycopg.connect(maint_url, autocommit=True, connect_timeout=3) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{target_db}"')
            conn.execute(f'REVOKE ALL ON DATABASE postgres FROM "{role}"')
            conn.execute(f'DROP ROLE IF EXISTS "{role}"')


class TestBareThrowawayDatabaseGetsProvisioned:
    """The exact issue #312 repro: a bare `CREATE DATABASE` with zero
    tables must not raise `UndefinedTable` after `ensure_pg_ready`."""

    def test_bare_database_reproduces_the_reported_defect_unfixed(
        self, bare_throwaway_db
    ) -> None:
        """Sanity check that the fixture really reproduces issue #312's
        exact symptom BEFORE the fix runs — a test that can never fail
        proves nothing."""
        with pytest.raises(psycopg.errors.UndefinedTable):
            with psycopg.connect(
                bare_throwaway_db, autocommit=True, connect_timeout=3
            ) as conn:
                conn.execute("SELECT 1 FROM memory_entities LIMIT 1")

    def test_ensure_pg_ready_provisions_every_required_table(
        self, bare_throwaway_db
    ) -> None:
        assert ensure_pg_ready(bare_throwaway_db) is True
        with psycopg.connect(
            bare_throwaway_db, autocommit=True, connect_timeout=3
        ) as conn:
            for table in _REQUIRED_TABLES:
                oid = conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]
                assert oid is not None, f"{table} was not provisioned"

    def test_a_provisioned_database_no_longer_raises_undefined_table(
        self, bare_throwaway_db
    ) -> None:
        ensure_pg_ready(bare_throwaway_db)
        with psycopg.connect(
            bare_throwaway_db, autocommit=True, connect_timeout=3
        ) as conn:
            row = conn.execute("SELECT COUNT(*) FROM memory_entities").fetchone()
        assert row == (0,)

    def test_provisioning_is_idempotent_on_a_second_call(
        self, bare_throwaway_db
    ) -> None:
        """The second call must be the cheap, hash-gated fast path — and,
        more importantly, must not fail or alter the outcome."""
        assert ensure_pg_ready(bare_throwaway_db) is True
        assert ensure_pg_ready(bare_throwaway_db) is True
        with psycopg.connect(
            bare_throwaway_db, autocommit=True, connect_timeout=3
        ) as conn:
            oid = conn.execute("SELECT to_regclass('memory_entities')").fetchone()[0]
        assert oid is not None


class TestMissingDatabaseGetsCreated:
    def test_ensure_pg_ready_creates_and_provisions_a_missing_database(
        self, nonexistent_db_url
    ) -> None:
        assert ensure_pg_ready(nonexistent_db_url) is True
        with psycopg.connect(
            nonexistent_db_url, autocommit=True, connect_timeout=3
        ) as conn:
            oid = conn.execute("SELECT to_regclass('memory_entities')").fetchone()[0]
        assert oid is not None


class TestGenuinelyUnreachableStillDegradesGracefully:
    def test_a_real_unreachable_server_returns_false_and_warns_once(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = ensure_pg_ready(
                "postgresql://127.0.0.1:1/cortex_312_definitely_unreachable"
            )
        assert result is False
        assert len(caught) == 1
        assert isinstance(caught[0].message, PostgresUnavailableWarning)


class TestPermissionDeniedFailsLoudlyNotSilently:
    def test_a_role_without_createdb_triggers_pytest_exit_not_a_skip(
        self, lowpriv_role_url
    ) -> None:
        """The defect this whole module exists to close: a real
        environment problem (no CREATEDB privilege) must abort the
        session with an actionable message, never quietly convert into a
        skip that would hide it. `_pytest.outcomes.Exit` is exactly what
        `pytest.exit(...)` raises — the same exception pytest itself
        catches at the session boundary to terminate cleanly.
        """
        with pytest.raises(_PytestExit) as excinfo:
            ensure_pg_ready(lowpriv_role_url)
        message = str(excinfo.value)
        assert "issue #312" in message
        assert "CREATEDB" in message
