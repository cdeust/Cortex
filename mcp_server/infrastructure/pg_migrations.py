"""Versioned PostgreSQL schema: the one migration path and the runtime check.

A schema version is an integer that only grows. ``SCHEMA_HASHES`` maps each
released version to the fingerprint of the full idempotent DDL set
(``get_all_ddl``) that defines it; a change to that DDL without a new version
fails ``tests_py/infrastructure/test_pg_migrations.py``. The database records
its version in ``schema_version`` and the fingerprint in ``schema_meta``.

Runtime processes only READ the state (``check_runtime``): a database at a
higher version than the code, at an unknown or lower one, or whose
``schema_meta`` was rewritten by an unversioned install is refused with an
explicit error, never migrated. The only exception is a database with no
Cortex schema at all (first run, nothing can be reading it). ``apply_schema``
is the explicit step (``python -m mcp_server.migrate``, the broker's start,
``scripts/setup_db.py``): under the schema advisory lock, it applies the DDL
and records the version only when every statement succeeded.

source: ADR-1112
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import tuple_row

from mcp_server.infrastructure.pg_schema import get_all_ddl
from mcp_server.infrastructure.pg_session_bounds import migration_name
from mcp_server.infrastructure.schema_versions import (
    SCHEMA_HASHES,
    SCHEMA_VERSION,
    MigrationFailedError,
    MigrationPrerequisiteError,
    SchemaState,
    check_runtime,
    code_revision,
)

logger = logging.getLogger("mcp_server.infrastructure.pg_store")

# source: ADR-0545 (the schema advisory lock key, unchanged)
SCHEMA_LOCK_ID = 1357020271
# source: ADR-0545
_SCHEMA_META_DDL = (
    "CREATE TABLE IF NOT EXISTS schema_meta ("
    " id integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),"
    " ddl_hash text NOT NULL,"
    " applied_at timestamptz NOT NULL DEFAULT now())"
)
# source: ADR-1112 (broker and versioned schema)
_SCHEMA_VERSION_DDL = (
    "CREATE TABLE IF NOT EXISTS schema_version ("
    " version integer PRIMARY KEY,"
    " ddl_hash text NOT NULL,"
    " code_revision text NOT NULL,"
    " applied_at timestamptz NOT NULL DEFAULT now())"
)
# source: ADR-1112 one catalog read decides first run vs existing schema
_STATE_SQL = (
    "SELECT to_regclass('public.schema_version') IS NOT NULL,"
    " to_regclass('public.schema_meta') IS NOT NULL,"
    " to_regclass('public.memories') IS NOT NULL"
)
# source: pg_schema.EXTENSIONS_DDL; experiment log entry 11 (DDL census)
REQUIRED_EXTENSIONS = ("vector", "pg_trgm")


def _one(conn: psycopg.Connection[Any], sql: str) -> tuple | None:
    with conn.cursor(row_factory=tuple_row) as cur:
        return cur.execute(sql).fetchone()  # type: ignore[arg-type]


def read_state(conn: psycopg.Connection[Any]) -> SchemaState:
    """Read the recorded schema state. Any database error propagates: a
    failed read is never taken for a first run (ADR-1112 residual path)."""
    flags = _one(conn, _STATE_SQL)
    assert flags is not None  # a SELECT without FROM returns one row
    has_version, has_meta, has_memories = flags
    version = None
    if has_version:
        row = _one(conn, "SELECT max(version) FROM schema_version")
        version = None if row is None else row[0]
    recorded = None
    if has_meta:
        row = _one(conn, "SELECT ddl_hash FROM schema_meta WHERE id = 1")
        recorded = None if row is None else row[0]
    fresh = not (has_version or has_meta or has_memories)
    return SchemaState(fresh=fresh, version=version, recorded_hash=recorded)


def _record(conn: psycopg.Connection[Any]) -> None:
    fingerprint = SCHEMA_HASHES[SCHEMA_VERSION]
    conn.execute(_SCHEMA_VERSION_DDL)
    conn.execute(_SCHEMA_META_DDL)
    conn.execute(
        "INSERT INTO schema_version (version, ddl_hash, code_revision)"
        " VALUES (%s, %s, %s) ON CONFLICT (version) DO UPDATE SET"
        " ddl_hash = EXCLUDED.ddl_hash, code_revision = EXCLUDED.code_revision,"
        " applied_at = now()",
        (SCHEMA_VERSION, fingerprint, code_revision()),
    )
    conn.execute(
        "INSERT INTO schema_meta (id, ddl_hash, applied_at) VALUES (1, %s, now())"
        " ON CONFLICT (id) DO UPDATE SET ddl_hash = EXCLUDED.ddl_hash,"
        " applied_at = EXCLUDED.applied_at",
        (fingerprint,),
    )


def _ensure_prerequisites(conn: psycopg.Connection[Any]) -> None:
    """Extensions first, as their own step.

    Measured (experiment log entry 11): an owner that is not a superuser
    cannot create ``vector`` (an untrusted extension), and on main that one
    failure cascaded into 58 (every table, index and function that needs the
    type). Here a missing extension the role cannot create stops the
    migration before any statement, with the one command an administrator
    runs. (Schema version 2 also loaded pg_trgm's library here, because
    ``recall_memories()`` declared ``SET pg_trgm.similarity_threshold``, which
    a non-superuser may create only once the library is loaded; version 3
    sets the threshold in the function body, so no session state is needed.)"""
    with conn.cursor(row_factory=tuple_row) as cur:
        present = {
            row[0]
            for row in cur.execute(
                "SELECT extname FROM pg_extension WHERE extname = ANY(%s)",
                (list(REQUIRED_EXTENSIONS),),
            ).fetchall()
        }
    for name in REQUIRED_EXTENSIONS:
        if name in present:
            continue
        try:
            conn.execute(
                sql.SQL("CREATE EXTENSION IF NOT EXISTS {}").format(
                    sql.Identifier(name)
                )
            )
        except psycopg.errors.InsufficientPrivilege as exc:
            raise MigrationPrerequisiteError(
                f"extension {name} is not installed and this role cannot create "
                f"it ({str(exc).splitlines()[0]}); as a superuser, run "
                f"'CREATE EXTENSION {name};' in this database, then migrate again. "
                "No statement was applied and nothing was recorded."
            ) from exc


def _apply_statements(conn: psycopg.Connection[Any]) -> int:
    failures: list[str] = []
    statements = get_all_ddl()
    for ddl in statements:
        try:
            conn.execute(ddl)
        except psycopg.Error as exc:
            failures.append(f"{ddl.strip().splitlines()[0][:60]}: {exc}")
    if failures:
        raise MigrationFailedError(
            f"{len(failures)} of {len(statements)} schema statements failed; the "
            f"version was not recorded. First: {failures[0]}",
            failures,
        )
    return len(statements)


def migrate_locked(conn: psycopg.Connection[Any]) -> int:
    """Bring ``conn``'s database to ``SCHEMA_VERSION`` under the advisory lock.

    Returns the number of DDL statements applied (0 when only the version
    was recorded, or nothing was needed). ``conn`` must be in autocommit.
    Raises ``SchemaTooNewError`` (no downgrade) or ``MigrationFailedError``.
    """
    conn.execute("SELECT pg_advisory_lock(%s)", (SCHEMA_LOCK_ID,))
    try:
        state = read_state(conn)
        found = state.effective_version
        if found is not None and found > SCHEMA_VERSION:
            check_runtime(state)  # raises SchemaTooNewError
        current_hash = state.recorded_hash == SCHEMA_HASHES[SCHEMA_VERSION]
        if found == SCHEMA_VERSION and current_hash:
            if state.version != SCHEMA_VERSION:
                _record(conn)
            return 0
        _ensure_prerequisites(conn)
        applied = _apply_statements(conn)
        _record(conn)
        return applied
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (SCHEMA_LOCK_ID,))


def apply_schema(database_url: str) -> int:
    """The explicit migration step on a dedicated connection; see
    ``migrate_locked``."""
    with psycopg.connect(
        database_url, autocommit=True, application_name=migration_name()
    ) as conn:
        return migrate_locked(conn)
