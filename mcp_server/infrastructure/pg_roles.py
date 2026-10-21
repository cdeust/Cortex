"""Least privilege in the database: a migration role and a runtime role.

The migration role owns the Cortex schema and is used only by the broker's
start-up migration step (``CORTEX_MIGRATION_DATABASE_URL``); the runtime
role, the one in ``DATABASE_URL`` that the broker's pool uses, holds no DDL
and no superuser: data access on the Cortex tables, views and sequences,
EXECUTE on its functions, and the temporary tables every role has by
default. After each migration the migration role grants exactly that to
the runtime role, so a table a migration adds is usable at the same start.

A user-supplied single URL keeps one role for both; doctor reports it.

source: ADR-1112 (Zero Trust boundary, least privilege); three-pillar audit
Track 0.3, probe B
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from mcp_server.infrastructure.pg_session_bounds import migration_name

# source: pg_schema (public holds the memory tables, wiki the wiki store)
CORTEX_SCHEMAS = ("public", "wiki")
# source: ADR-1112 the environment variable naming the migration role's URL
MIGRATION_URL_ENVIRONMENT = "CORTEX_MIGRATION_DATABASE_URL"


def role_of(database_url: str) -> str:
    """The role a URL logs in as (libpq's default: the OS user)."""
    user = conninfo_to_dict(database_url).get("user")
    if user:
        return str(user)
    import getpass  # noqa: PLC0415 — libpq's own default when the URL names none

    return getpass.getuser()


def _grants(role: str) -> list[sql.Composed]:
    who = sql.Identifier(role)
    statements: list[sql.Composed] = []
    for name in CORTEX_SCHEMAS:
        schema = sql.Identifier(name)
        statements += [
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(schema, who),
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {} TO {}"
            ).format(schema, who),
            sql.SQL(
                "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA {} TO {}"
            ).format(schema, who),
            sql.SQL("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {} TO {}").format(
                schema, who
            ),
        ]
    return statements


def grant_runtime(migration_url: str, runtime_role: str) -> int:
    """Grant the runtime role its data access, in one transaction, as the
    migration role (the owner). Returns the number of statements run."""
    statements = _grants(runtime_role)
    with psycopg.connect(migration_url, application_name=migration_name()) as conn:
        with conn.transaction():
            for statement in statements:
                conn.execute(statement)
    return len(statements)


def migration_url(runtime_url: str, environment: Any) -> str:
    """The URL the migration step uses: its own role when configured."""
    return environment.get(MIGRATION_URL_ENVIRONMENT) or runtime_url


def provision(
    admin_url: str, database: str, migrate_role: str, runtime_role: str
) -> None:
    """As an administrator: the two login roles, the database owned by the
    migration role, and the extensions the schema needs (``vector`` is not a
    trusted extension, so only an administrator may create it). Idempotent.
    Passwords are the administrator's business (``ALTER ROLE ... PASSWORD``
    or a ``.pgpass`` entry); none is set or printed here."""
    with psycopg.connect(admin_url, autocommit=True) as conn:
        for role in (migrate_role, runtime_role):
            _create_login_role(conn, role)
        present = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (database,)
        ).fetchone()
        if present is None:
            conn.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(database), sql.Identifier(migrate_role)
                )
            )
        conn.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(database), sql.Identifier(runtime_role)
            )
        )
    _prepare_database(admin_url.rpartition("/")[0] + "/" + database, migrate_role)


def _create_login_role(conn: psycopg.Connection[Any], role: str) -> None:
    exists = conn.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)
    ).fetchone()
    if exists is None:
        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
                sql.Identifier(role)
            )
        )


def _prepare_database(target: str, migrate_role: str) -> None:
    """In the new database, as the administrator: the extensions, and DDL in
    ``public`` for the migration role only."""
    with psycopg.connect(target, autocommit=True) as conn:
        for extension in ("vector", "pg_trgm"):
            conn.execute(
                sql.SQL("CREATE EXTENSION IF NOT EXISTS {}").format(
                    sql.Identifier(extension)
                )
            )
        # PostgreSQL 14 and older let PUBLIC create in public: no DDL for
        # anyone but the owner (15+ already revokes it)
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        conn.execute(
            sql.SQL("GRANT CREATE ON SCHEMA public TO {}").format(
                sql.Identifier(migrate_role)
            )
        )
