"""Clients get their store from the broker (ADR-1112 increment 5).

Without ``CORTEX_STORE_IN_PROCESS`` (set only in the broker and by the test
harness's default) the store factory returns a ``BrokerStore``. Schema
decisions are the broker's: it migrates an older schema at start, and a
newer one makes it refuse every client with the same "upgrade Cortex" error
an in-process store raised; nothing falls back to SQLite.

source: ADR-1112 decisions 1, 5 and 7
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator

import pytest

from mcp_server.infrastructure import broker_endpoint
from mcp_server.infrastructure.broker_client import BrokerStore
from mcp_server.infrastructure.schema_versions import SCHEMA_VERSION, SchemaTooNewError
from tests_py import _pg_throwaway_db
from tests_py.conftest import _USE_PG

psycopg = pytest.importorskip("psycopg")

pytestmark = [
    pytest.mark.skipif(not _USE_PG, reason="requires isolated PostgreSQL"),
    pytest.mark.skipif(sys.platform == "win32", reason="Unix transport"),
]


@pytest.fixture
def scratch_url() -> Iterator[str]:
    base = os.environ["DATABASE_URL"]
    maint = _pg_throwaway_db.maintenance_url(base)
    name = f"cortex_test_pw{os.getpid()}_{os.urandom(4).hex()}"
    with psycopg.connect(maint, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    try:
        yield base.rpartition("/")[0] + "/" + name
    finally:
        _pg_throwaway_db.drop_isolated_database(maint, name)


def _read(url: str, sql: str):
    with psycopg.connect(url, autocommit=True) as conn:
        return conn.execute(sql).fetchall()


def test_the_factory_serves_the_store_through_the_broker(broker_env, monkeypatch):
    from mcp_server.infrastructure import memory_store  # noqa: PLC0415

    root, children = broker_env
    monkeypatch.delenv("CORTEX_STORE_IN_PROCESS", raising=False)
    monkeypatch.setattr(memory_store, "CLAUDE_DIR", root)
    store, error = memory_store._try_pg_verbose(os.environ["DATABASE_URL"])  # noqa: SLF001
    try:
        assert error is None and isinstance(store, BrokerStore)
        assert store.get_memory(-1) is None
        assert len(children) == 1 and store.broker_pid() == children[0].pid
    finally:
        store.close()


def test_the_broker_migrates_an_empty_database_at_start(broker_env, scratch_url):
    root, _ = broker_env
    broker_endpoint.broker_store(scratch_url, root, "test").close()
    assert _read(scratch_url, "SELECT max(version) FROM schema_version") == [
        (SCHEMA_VERSION,)
    ]


def test_a_newer_schema_reaches_the_client_as_upgrade_cortex(broker_env, scratch_url):
    """The broker cannot open the store; every client is told why, with the
    in-process store's own error type and message, and nothing is changed."""
    from mcp_server.infrastructure.pg_migrations import apply_schema  # noqa: PLC0415

    root, children = broker_env
    apply_schema(scratch_url)
    with psycopg.connect(scratch_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO schema_version VALUES (%s, 'future', 'future', now())",
            (SCHEMA_VERSION + 1,),
        )
    with pytest.raises(SchemaTooNewError, match="upgrade Cortex"):
        broker_endpoint.broker_store(scratch_url, root, "test")
    assert children[0].wait(timeout=20) == 0  # it exits once it has said why
    assert _read(scratch_url, "SELECT max(version) FROM schema_version") == [
        (SCHEMA_VERSION + 1,)
    ]
