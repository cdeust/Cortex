"""Ensure the resolved test-database URL is reachable AND schema-provisioned
before any PostgreSQL-gated test in this session runs (issue #312).

ROOT CAUSE: `tests_py/_pg_throwaway_db.py`'s per-process throwaway database
(and, equally, an explicit `CORTEX_TEST_DATABASE_URL` pointed at a database
that was never migrated) is a bare `CREATE DATABASE` — zero tables. Before
the #219 store-isolation work, these tests ran against the real `cortex`
database, which already carried a full schema; isolation redirected them to
a throwaway target without ever provisioning it. In CI's shared, persistent
`cortex` database, the gap is invisible: SOME earlier test in the same
session constructs a `PgMemoryStore()` first and incidentally provisions
the schema for everyone after it. Standalone or narrowly-scoped local runs
have no such earlier test, so the very first raw-SQL query against e.g.
`memory_entities` dies with `psycopg.errors.UndefinedTable` — accidental,
execution-order-dependent provisioning, not deterministic isolation.

PR #319 proposed detecting this condition and skipping. That is the wrong
fix (issue #312, maintainer directive): a skip converts thousands of real
assertions into a silent pass and permanently enshrines the local-vs-CI
divergence. This module makes provisioning DETERMINISTIC instead — every
session ensures its own resolved database is ready, exactly the same way
CI accidentally ends up ready, without depending on which test happens to
run first.

Reuses the production migration path — never a hand-copied schema.
Constructing `PgMemoryStore(database_url=...)` under the hood runs
`_init_schema()`, which applies `pg_schema.get_all_ddl()` idempotently
(hash-gated: a DB already at the code's revision costs one indexed
SELECT). This is the exact same call `mcp_server/migrate.py` makes to
migrate a live install — "constructing PgMemoryStore IS the migration"
(that module's own docstring) — so a test session and a real deployment
can never drift onto two different schemas.

Genuinely-absent PostgreSQL (driver not installed, or the server itself
unreachable) still degrades to a skip, exactly as documented before this
change. Reachable-but-unprovisioned (the actual #312 defect: server up,
named database missing or empty) no longer skips — it gets created and/or
migrated. A REAL environment error while doing so (no CREATEDB privilege,
a required extension the connecting role cannot install) is reported
loudly via `pytest.exit` — the same fail-closed idiom already used by this
file's siblings, `guard_against_populated_db` /
`guard_against_real_data_roots` in `tests_py/_pg_safety_guards.py` — never
downgraded to a silent skip; that downgrade is exactly the class of bug
this module exists to close.

`PostgresUnavailableWarning` carries over PR #319's `SchemaSkipWarning`
idea (a `UserWarning` subclass raised via `warnings.warn`, printed in
pytest's warnings summary regardless of `-q` verbosity, unlike a skip
*reason* which needs `-rs`/`-ra`) retargeted at the one skip-worthy
condition that survives this change: genuine unavailability. It fires
exactly once per session, here, rather than once per PG-gated test module
— fourteen-plus files in this suite skip on the shared `_USE_PG` flag
(`tests_py/conftest.py`), so a per-module warning would be fourteen-plus
near-duplicate lines for one underlying condition.
"""

from __future__ import annotations

import warnings

import pytest

from tests_py._pg_throwaway_db import maintenance_url


class PostgresUnavailableWarning(UserWarning):
    """PostgreSQL is not reachable at all this session (server down, or
    the `psycopg` driver itself is not installed — the ordinary,
    expected state of a SQLite-only install). Every PG-gated test skips,
    as documented; this warning only makes that fact visible in the
    warnings summary instead of requiring `-rs`/`-ra` to see the reason.
    """


def _can_connect(url: str) -> bool:
    """True iff a direct connection to `url` succeeds.

    Every failure mode — driver absent, server down, auth rejected, the
    target database not existing — reads as False here; distinguishing
    WHY is `ensure_pg_ready`'s job (it tries a maintenance connection
    next), not this probe's.
    """
    try:
        import psycopg  # noqa: PLC0415 — deferred: optional [postgresql] extra, absent on SQLite-only installs

        with psycopg.connect(url, autocommit=True, connect_timeout=3):
            pass
        return True
    except Exception:  # noqa: BLE001 — reachability probe; every failure reads as "not reachable now" (mirrors tests_py/conftest.py's own _pg_available)
        return False


def _database_name(url: str) -> str:
    """The database-name segment of a ``postgresql://`` URL.

    Same parsing idiom as `_pg_throwaway_db.maintenance_url`: the query
    string is dropped FIRST (``partition("?")``), then the name is
    everything after the rightmost ``/`` in what remains
    (``rpartition("/")``). Order matters: a query string carrying its
    own ``/`` (e.g. a file-path option) would otherwise be mistaken for
    the database-name separator if the rightmost-``/`` split ran first —
    see that module's test for the exact scenario this ordering avoids.
    """
    base, _, _query = url.partition("?")
    _prefix, _, name = base.rpartition("/")
    return name


def _create_database(url: str) -> None:
    """Create the database named in `url` via a maintenance connection.

    Pre: the PostgreSQL SERVER is reachable (the caller has already
    confirmed this by connecting to its maintenance database) — `url`'s
    own database is the only thing missing.
    Post: the database exists. A database that cannot be created (no
    CREATEDB privilege, quota, any other server-side refusal) aborts the
    session via `pytest.exit`, naming the URL and the concrete fix —
    never a silent skip (issue #312).
    """
    import psycopg  # noqa: PLC0415 — deferred: optional [postgresql] extra, absent on SQLite-only installs

    name = _database_name(url)
    maint = maintenance_url(url)
    try:
        with psycopg.connect(maint, autocommit=True, connect_timeout=3) as conn:
            exists = conn.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
            ).fetchone()
            if exists:
                return
            conn.execute(f'CREATE DATABASE "{name}"')
    except psycopg.errors.DuplicateDatabase:
        return  # a concurrent process created it between our SELECT and CREATE
    except Exception as exc:  # noqa: BLE001 — last-resort boundary: reported via pytest.exit below, never swallowed
        pytest.exit(
            f"REFUSING to run: PostgreSQL is reachable at {maint!r} but "
            f"database {name!r} does not exist and could not be created: "
            f"{exc}. Fix: grant CREATEDB to the connecting role "
            f"(ALTER ROLE <role> CREATEDB;) or create it manually "
            f"(createdb {name}), then re-run (issue #312).",
            returncode=2,
        )


def _provision_schema(url: str) -> None:
    """Apply Cortex's production DDL to `url` via the exact path every
    real construction already uses — never a second, hand-copied
    definition of the schema (issue #312's explicit requirement; see
    `mcp_server/migrate.py`, which does the identical thing to migrate a
    live install: "constructing PgMemoryStore IS the migration").

    Idempotent: `PgMemoryStore._init_schema` hash-gates its DDL apply, so
    a database already at the code's revision costs one indexed SELECT
    — this is cheap to call on every session, not just the first.
    """
    from mcp_server.infrastructure.pg_store import (  # noqa: PLC0415 — deferred: hard-imports pgvector/psycopg/psycopg_pool, absent on SQLite-only installs
        PgMemoryStore,
    )

    try:
        store = PgMemoryStore(database_url=url)
    except Exception as exc:  # noqa: BLE001 — last-resort boundary: reported via pytest.exit below, never swallowed
        pytest.exit(
            f"REFUSING to run: PostgreSQL database {url!r} is reachable "
            f"but applying the production schema failed: {exc}. Fix: "
            "check the connecting role's privileges (CREATE on the "
            "database, CREATE EXTENSION for vector/pg_trgm) and "
            "PostgreSQL's own logs, then re-run (issue #312).",
            returncode=2,
        )
        return
    store.close()


def ensure_pg_ready(url: str) -> bool:
    """Session-start gate for issue #312.

    Pre: none — `url` may point at a database that does not exist yet.
    Post: returns True iff `url` is ready for PG-gated tests this session
    — reachable AND schema-provisioned, via the production DDL path.
    Returns False only when PostgreSQL cannot be reached at all (driver
    absent, or the server itself unreachable) — the ordinary, documented
    skip case, unchanged in outcome, now paired with one
    `PostgresUnavailableWarning` so a session-wide skip is visible in the
    warnings summary instead of requiring `-rs`/`-ra`.
    Aborts the session via `pytest.exit` (does not return) when
    PostgreSQL IS reachable but bringing `url` to a runnable state fails
    for any other reason — downgrading that to a skip is exactly the
    defect this module exists to close.
    """
    if _can_connect(url):
        _provision_schema(url)
        return True
    if not _can_connect(maintenance_url(url)):
        warnings.warn(
            PostgresUnavailableWarning(
                f"PostgreSQL is not reachable at {url!r} this session — "
                "PostgreSQL-gated tests will skip (expected on a "
                "SQLite-only install; if this environment is supposed to "
                "have PostgreSQL, that absence is the problem to fix)."
            ),
            stacklevel=2,
        )
        return False
    _create_database(url)
    _provision_schema(url)
    return True
