"""Standalone schema-migration entry point for Cortex.

source: ADR-0637"""

from __future__ import annotations

import sys
from mcp_server.infrastructure.pg_schema import get_all_ddl


def _probe_was_current(url: str, target_hash: str) -> bool:
    """Read the pre-migration schema state on a short-lived probe connection.

    source: ADR-0637"""
    import psycopg  # noqa: PLC0415 — source: ADR-0637
    from psycopg.rows import DictRow, dict_row  # noqa: PLC0415 — source: ADR-0637

    from mcp_server.infrastructure.pg_store import read_schema_hash  # noqa: PLC0415 — source: ADR-0637

    with psycopg.Connection[DictRow].connect(
        url,
        # source: ADR-0637
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
    from mcp_server.infrastructure.pg_store import (  # noqa: PLC0415 — source: ADR-0637
        PgMemoryStore,
        _get_database_url,
        compute_ddl_hash,
    )

    url = _get_database_url()
    target_hash = compute_ddl_hash()

    try:
        was_current = _probe_was_current(url, target_hash)
    except Exception as exc:  # noqa: BLE001 — source: ADR-0637
        print(f"cortex-migrate: cannot connect to database: {exc}", file=sys.stderr)
        return 1

    store: PgMemoryStore | None = None
    try:
        # Constructing PgMemoryStore IS the migration: __init__ calls
        # _init_schema(), which applies get_all_ddl() under the advisory
        # lock iff the recorded hash is stale. Single source of truth —
        # this module never re-applies DDL itself.
        store = PgMemoryStore(database_url=url)
    except Exception as exc:  # noqa: BLE001 — source: ADR-0637
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
