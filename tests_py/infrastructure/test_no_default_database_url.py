"""Issue #704, library residual: no default DATABASE_URL anywhere in code.

The hook and server entry points already settle the backend before
settings bind (tests_py/hooks/test_entry_fresh_backend.py). These tests pin
the library paths that still read ``MemorySettings.DATABASE_URL`` directly:
with no named URL, nothing may try PostgreSQL, and no raw connection may be
opened with an empty conninfo (libpq would then reach whatever local server
its defaults point to).
"""

from __future__ import annotations

import os

import pytest

import mcp_server.infrastructure.memory_store as memory_store_module
from mcp_server.infrastructure.memory_config import MemorySettings, get_memory_settings


@pytest.fixture
def no_named_url(monkeypatch, tmp_path):
    """No URL, backend or marker from any source; every PostgreSQL attempt
    fails the test.

    CI's unit job exports ``CORTEX_MEMORY_STORE_BACKEND=postgresql``
    (scripts/ci_unit.sh), and commands now settle the backend marker first,
    so both are isolated here; the environment is restored whole because
    ``settle_backend`` writes keys of its own.
    """
    from mcp_server.infrastructure import backend_marker

    saved = dict(os.environ)
    for name in (
        "DATABASE_URL",
        "CORTEX_MEMORY_DATABASE_URL",
        "CORTEX_MEMORY_STORE_BACKEND",
        "CORTEX_ALLOW_SQLITE_FALLBACK",
    ):
        os.environ.pop(name, None)
    fresh = tmp_path / "methodology"
    fresh.mkdir()
    monkeypatch.setattr(backend_marker, "BACKEND_MARKER_PATH", fresh / "backend.json")
    monkeypatch.setattr(
        memory_store_module,
        "_try_pg_verbose",
        lambda url: pytest.fail(f"PostgreSQL was tried at {url!r}"),
    )
    get_memory_settings.cache_clear()
    yield monkeypatch
    os.environ.clear()
    os.environ.update(saved)
    get_memory_settings.cache_clear()


def test_settings_carry_no_default_url(no_named_url):
    assert MemorySettings().DATABASE_URL == ""


def test_settings_url_comes_only_from_the_prefixed_variable(no_named_url):
    no_named_url.setenv("CORTEX_MEMORY_DATABASE_URL", "postgresql://db.invalid/x")
    assert MemorySettings().DATABASE_URL == "postgresql://db.invalid/x"


@pytest.mark.parametrize("runtime", ["cli", "cowork"])
def test_auto_without_url_is_sqlite_with_no_connection_attempt(
    no_named_url, tmp_path, runtime
):
    """Before #704 the CLI runtime mapped auto to PostgreSQL and tried
    ``postgresql://127.0.0.1:5432/cortex``; a local ``cortex`` database
    that answered was then used without anyone configuring it."""
    no_named_url.setenv("CORTEX_RUNTIME", runtime)
    no_named_url.setenv("CORTEX_MEMORY_STORE_BACKEND", "auto")
    store = memory_store_module._construct_store(db_path=str(tmp_path / "m.db"))
    try:
        assert type(store).__name__ == "SqliteMemoryStore"
    finally:
        store.close()


def test_postgresql_backend_without_url_refuses(no_named_url):
    """An explicit PostgreSQL backend with no URL is a configuration error,
    not a silent SQLite store and not a connection to a guessed server."""
    no_named_url.setenv("CORTEX_MEMORY_STORE_BACKEND", "postgresql")
    with pytest.raises(RuntimeError, match="no database URL is configured"):
        memory_store_module._construct_store()


def test_cache_key_of_cli_auto_without_url_is_not_postgresql(no_named_url):
    no_named_url.setenv("CORTEX_RUNTIME", "cli")
    no_named_url.setenv("CORTEX_MEMORY_STORE_BACKEND", "auto")
    backend, url = memory_store_module._resolve_backend_url("", 384, None)
    assert (backend, url) == ("auto", "")


def test_raw_url_resolver_refuses_an_empty_conninfo(no_named_url):
    pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")
    from mcp_server.infrastructure.pg_store_ddl import _get_database_url

    with pytest.raises(ValueError, match="no PostgreSQL URL configured"):
        _get_database_url()


def test_migrate_reports_a_missing_url_on_its_exit_contract(no_named_url, capsys):
    pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")
    from mcp_server.migrate import _run

    assert _run() == 1
    assert "no PostgreSQL URL configured" in capsys.readouterr().err


def test_briefing_without_url_borrows_the_shared_store(no_named_url):
    from mcp_server.hooks import agent_briefing_query

    sentinel = object()
    no_named_url.setenv("CORTEX_MEMORY_STORE_BACKEND", "auto")
    no_named_url.setattr(memory_store_module, "get_shared_store", lambda: sentinel)
    connection = agent_briefing_query._connect()
    assert connection.store is sentinel


def test_briefing_postgresql_without_url_opens_nothing(no_named_url):
    pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")
    import mcp_server.infrastructure.db_connect as db_connect
    from mcp_server.hooks import agent_briefing_query

    no_named_url.setenv("CORTEX_MEMORY_STORE_BACKEND", "postgresql")
    no_named_url.setattr(
        db_connect, "pg_connect", lambda *a, **k: pytest.fail("pg_connect called")
    )
    assert agent_briefing_query._connect() is None
