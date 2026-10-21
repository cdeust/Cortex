"""An existing database gets the tie-broken recall_memories() on upgrade.

The explicit migration step, ``pg_migrations.apply_schema`` (ADR-1112; it
was ``PgDdlMixin._init_schema`` on store open before), re-applies the whole
DDL set when the recorded ``schema_meta.ddl_hash`` differs from the code's
(ADR-0545). Here the database is put back in origin/main's state:
recall_memories() without the ADR-1106 tie-break and a foreign hash.
Migrating must replace the function body. The assertion reads the body
itself, not the hash: ``_apply_ddl_locked`` logs a failing statement and
records the hash anyway.

Live PG (throwaway test database via conftest); skipped on SQLite.

source: ADR-1106
source: ADR-1109
"""

from __future__ import annotations

import os
import re

import pytest

from mcp_server.infrastructure.pg_schema import (
    RECALL_MEMORIES_LAZY_FN,
    _split_statements,
)
from tests_py.conftest import _USE_PG

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.skipif(not _USE_PG, reason="requires isolated PostgreSQL")

_TIE_BREAK = "c.created_at DESC, tw.id DESC"


def main_body() -> str:
    """recall_memories() as on origin/main 6cecb7c2: no tie-break anywhere."""
    body = re.sub(
        r",\s*c\.created_at DESC,\s*(?:c|tw)\.id DESC", "", RECALL_MEMORIES_LAZY_FN
    )
    body = re.sub(r"(c\.created_at DESC),\s*c\.id DESC", r"\1", body)
    assert not re.search(r"(?:c|tw)\.id DESC", body)
    return body


def function_body(conn) -> str:
    return conn.execute(
        "SELECT pg_get_functiondef('recall_memories'::regproc)"
    ).fetchone()[0]


def install(conn, ddl: str) -> None:
    for statement in _split_statements(ddl):
        conn.execute(statement)


def test_migrating_replaces_the_old_recall_function():
    from mcp_server.infrastructure.pg_store import (  # noqa: PLC0415 — PG-only import
        compute_ddl_hash,
    )
    from mcp_server.infrastructure.pg_migrations import apply_schema  # noqa: PLC0415 — PG-only import

    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url, autocommit=True) as conn:
        install(conn, main_body())
        conn.execute("UPDATE schema_meta SET ddl_hash = 'origin/main 6cecb7c2'")
        assert _TIE_BREAK not in function_body(conn)
    try:
        apply_schema(url)
        with psycopg.connect(url, autocommit=True) as conn:
            assert _TIE_BREAK in function_body(conn)
            recorded = conn.execute("SELECT ddl_hash FROM schema_meta").fetchone()[0]
            assert recorded == compute_ddl_hash()
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            install(conn, RECALL_MEMORIES_LAZY_FN)


def b2e63876_body() -> str:
    """recall_memories() as on origin/main b2e63876: every pool cut by LIMIT."""
    body = RECALL_MEMORIES_LAZY_FN.replace(
        "FETCH FIRST (v_pool) ROWS WITH TIES", "LIMIT v_pool"
    )
    assert "ROWS WITH TIES" not in body
    return body


def test_migrating_installs_the_tie_keeping_pools():
    """ADR-1109: the pools' WITH TIES reaches databases created before it."""
    from mcp_server.infrastructure.pg_store import (  # noqa: PLC0415 — PG-only import
        compute_ddl_hash,
    )
    from mcp_server.infrastructure.pg_migrations import apply_schema  # noqa: PLC0415 — PG-only import

    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url, autocommit=True) as conn:
        install(conn, b2e63876_body())
        conn.execute("UPDATE schema_meta SET ddl_hash = 'origin/main b2e63876'")
        assert "ROWS WITH TIES" not in function_body(conn)
    try:
        apply_schema(url)
        with psycopg.connect(url, autocommit=True) as conn:
            assert function_body(conn).count("ROWS WITH TIES") == 5
            recorded = conn.execute("SELECT ddl_hash FROM schema_meta").fetchone()[0]
            assert recorded == compute_ddl_hash()
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            install(conn, RECALL_MEMORIES_LAZY_FN)
