"""Standalone schema-migration entry point for Cortex.

Applies Cortex's PostgreSQL schema (``pg_schema.get_all_ddl()``) via the
exact same hash-gated, advisory-lock-serialized path
``PgMemoryStore._init_schema`` runs at construction — this module never
re-derives the DDL set or the migration algorithm, it only decides
*whether a migration happened* so it can report an accurate summary line,
using the read-only helpers ``pg_store.compute_ddl_hash`` /
``pg_store.read_schema_hash`` (the same functions ``_init_schema`` itself
calls).

Exists so a caller can force a schema migration WITHOUT booting the full
MCP server (FastMCP, the sentence-transformers embedding model, tool
registries) — e.g. the cortex-viz plugin, which detects an old schema
from its read-only PG connection and needs a lightweight way to bring it
current.

Invocation:
    python3 -m mcp_server.migrate

DATABASE_URL resolution is identical to the MCP server's — both call
``mcp_server.infrastructure.pg_store._get_database_url()``, so this entry
point and the server never disagree on which database they're pointed
at (env ``DATABASE_URL``, falling back to the packaged default
``postgresql://127.0.0.1:5432/cortex``).

Contract (frozen — consumed by the cortex-viz plugin):
    DATABASE_URL=<url> python3 -m mcp_server.migrate
    exit 0  -> no exception was raised while resolving/connecting/applying
               the DDL. stdout carries exactly one summary line:
                 "cortex-migrate: schema up to date"      (hash unchanged)
                 "cortex-migrate: applied N statements"   (hash was stale)
               Note this is NOT a guarantee that every individual DDL
               statement succeeded: ``_init_schema`` logs and skips any
               single statement that raises rather than aborting (see
               pg_store.py), so "applied N statements" means "the full
               DDL set was submitted", not "N statements each verified
               successful" — check the MCP server's own log for
               per-statement warnings if a downstream query then fails.
    exit 1  -> connecting to the database itself failed, or constructing
               PgMemoryStore raised for a reason other than a per-
               statement DDL failure (auth, network, driver install).
               stderr carries a one-line reason.
               No corrupted state is left: every statement in
               get_all_ddl() is independently idempotent (CREATE TABLE
               IF NOT EXISTS, CREATE OR REPLACE FUNCTION, guarded
               ALTER TABLE ADD COLUMN — see pg_schema.py), so re-running
               this entry point after a failure is always safe.

Not a single PostgreSQL transaction: get_all_ddl() contains no
transaction-hostile statements (no CREATE INDEX CONCURRENTLY — verified
against pg_schema.py), so each DDL statement commits independently under
autocommit, exactly as PgMemoryStore._init_schema already does. Atomicity
is provided by idempotence + the advisory lock (_SCHEMA_LOCK_ID in
pg_store.py), not by a wrapping transaction — a partial apply is safe to
resume because a second run reapplies every statement and every
statement tolerates being re-run.
"""

from __future__ import annotations

import sys
from mcp_server.infrastructure.pg_schema import get_all_ddl


def _probe_was_current(url: str, target_hash: str) -> bool:
    """Read the pre-migration schema state on a short-lived probe connection.

    Pre: ``url`` is a PostgreSQL DSN; ``target_hash`` is
    ``compute_ddl_hash()``'s current value. Opens and closes its OWN
    connection — never ``PgMemoryStore``'s, which does not exist yet at
    call time — so the result reflects what was true BEFORE this process
    touches the DB, not after ``_init_schema`` may have already migrated
    it. Uses ``read_schema_hash``, the same read ``_init_schema`` itself
    performs — single source of truth, just invoked earlier.
    Post: returns True iff the recorded ``schema_meta.ddl_hash`` already
    equals ``target_hash``. Raises whatever ``psycopg.connect`` raises on
    a connection failure — the caller catches it once, this function does
    not swallow it, so "cannot connect" and "migration failed" stay two
    distinct, separately-tested error paths (see module docstring).
    """
    import psycopg  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working
    from psycopg.rows import dict_row  # noqa: PLC0415 — optional dependency ([postgresql] extra); imported where used so environments without it keep working

    from mcp_server.infrastructure.pg_store import read_schema_hash  # noqa: PLC0415 — deferred: module hard-imports pgvector/psycopg/psycopg_pool at top level; hoisting would break installs without it

    with psycopg.connect(
        url,
        # source: doctor.py::_pg_connection / doctor_mcp.py:458 use
        # connect_timeout=5 for a live health-check probe; this probe is
        # the same kind of short read, so it matches that convention
        # rather than inventing a new one.
        connect_timeout=5,
        autocommit=True,
        row_factory=dict_row,
    ) as probe:
        return read_schema_hash(probe) == target_hash


def _run() -> int:
    """Resolve DATABASE_URL, connect, and migrate schema to the code's revision.

    Pre: none required from the caller; DATABASE_URL is optional (see
    module docstring for the resolution order).
    Post: exactly one line printed to stdout on success (return 0), or
    exactly one line to stderr on failure (return 1). Never raises —
    every exception is caught and mapped to the frozen exit contract.
    """
    from mcp_server.infrastructure.pg_store import (  # noqa: PLC0415 — deferred: module hard-imports pgvector/psycopg/psycopg_pool at top level; hoisting would break installs without it
        PgMemoryStore,
        _get_database_url,
        compute_ddl_hash,
    )

    url = _get_database_url()
    target_hash = compute_ddl_hash()

    try:
        was_current = _probe_was_current(url, target_hash)
    except Exception as exc:  # noqa: BLE001 — failure is reported to stderr; execution degrades, never crashes
        print(f"cortex-migrate: cannot connect to database: {exc}", file=sys.stderr)
        return 1

    store: PgMemoryStore | None = None
    try:
        # Constructing PgMemoryStore IS the migration: __init__ calls
        # _init_schema(), which applies get_all_ddl() under the advisory
        # lock iff the recorded hash is stale. Single source of truth —
        # this module never re-applies DDL itself.
        store = PgMemoryStore(database_url=url)
    except Exception as exc:  # noqa: BLE001 — failure is reported to stderr; execution degrades, never crashes
        print(f"cortex-migrate: schema migration failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()

    if was_current:
        print("cortex-migrate: schema up to date")
    else:
        print(f"cortex-migrate: applied {len(get_all_ddl())} statements")
    return 0


def main() -> int:
    return _run()


if __name__ == "__main__":
    sys.exit(main())
