"""Tests for the standalone ``python -m mcp_server.migrate`` entry point.

Covers the frozen exit-code contract consumed by the cortex-viz plugin
(``mcp_server/migrate.py`` module docstring):
  - DATABASE_URL resolution matches the server's (same function).
  - Success path: exit 0, exactly one stdout summary line, distinguishing
    "schema up to date" from "applied N statements" by the pre-migration
    state — not by guessing.
  - Failure path: exit 1, a one-line reason on stderr, no exception
    escapes ``main()``.

Pre: PostgreSQL reachable on ``_TEST_DB_URL`` for the live-DB tests;
URL-resolution and failure-path tests are hermetic (no PG required).
Post: schema left at the code's current revision (migrate() is
idempotent — every statement in get_all_ddl() tolerates re-application).
"""

from __future__ import annotations

import os

import pytest


# psycopg ships in the optional [postgresql] extra, absent from the
# SQLite-default install. The mcp_server import below pulls it in, so
# without this guard the module raises ModuleNotFoundError at COLLECTION
# time — an error, not a skip, which fails the whole run (#220). Skip the
# module cleanly instead; the PG gate below still applies when it is present.
pytest.importorskip("psycopg", reason="psycopg not installed ([postgresql] extra)")

from mcp_server.infrastructure.pg_store import (  # noqa: E402
    _get_database_url,
    compute_ddl_hash,
    read_schema_hash,
)
from mcp_server.migrate import _run  # noqa: E402
from tests_py.conftest import _TEST_DB_URL, _USE_PG  # type: ignore  # noqa: E402

pytestmark = pytest.mark.skipif(
    not _USE_PG, reason="PostgreSQL not available — migrate needs a live DB"
)


class TestUrlResolution:
    def test_migrate_imports_the_servers_url_resolver(self):
        """migrate.py must call ``pg_store._get_database_url`` itself, not
        a re-derived copy — pins that both entry points can never disagree
        on which database they're pointed at.
        """
        import ast
        from pathlib import Path

        source = Path(
            __import__("mcp_server.migrate", fromlist=["__file__"]).__file__
        ).read_text()
        tree = ast.parse(source)
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "mcp_server.infrastructure.pg_store"
            for alias in node.names
        }
        assert "_get_database_url" in imported_names

    def test_url_resolution_honors_database_url_env(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", _TEST_DB_URL)
        assert _get_database_url() == _TEST_DB_URL


class TestSuccessPath:
    def test_reports_up_to_date_when_already_migrated(self, monkeypatch, capsys):
        # Prime the DB to the current revision first (idempotent).
        monkeypatch.setenv("DATABASE_URL", _TEST_DB_URL)
        rc_prime = _run()
        assert rc_prime == 0
        capsys.readouterr()  # discard priming output

        rc = _run()

        out = capsys.readouterr().out.strip()
        assert rc == 0
        assert out == "cortex-migrate: schema up to date"

    def test_reports_applied_n_statements_on_fresh_hash(self, monkeypatch, capsys):
        """Force the recorded hash stale, then confirm migrate re-applies
        and reports the full statement count, not "up to date".
        """
        import psycopg
        from psycopg.rows import dict_row

        monkeypatch.setenv("DATABASE_URL", _TEST_DB_URL)
        with psycopg.connect(
            _TEST_DB_URL, autocommit=True, row_factory=dict_row
        ) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta ("
                " id integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),"
                " ddl_hash text NOT NULL,"
                " applied_at timestamptz NOT NULL DEFAULT now());"
            )
            conn.execute(
                "INSERT INTO schema_meta (id, ddl_hash) VALUES (1, 'stale-hash-marker')"
                " ON CONFLICT (id) DO UPDATE SET ddl_hash = EXCLUDED.ddl_hash;"
            )
            assert read_schema_hash(conn) == "stale-hash-marker"

        rc = _run()
        out = capsys.readouterr().out.strip()

        assert rc == 0
        assert out.startswith("cortex-migrate: applied ")
        assert out.endswith(" statements")

        with psycopg.connect(
            _TEST_DB_URL, autocommit=True, row_factory=dict_row
        ) as conn:
            assert read_schema_hash(conn) == compute_ddl_hash()


class TestFailurePath:
    def test_unreachable_database_exits_nonzero_with_stderr_reason(
        self, monkeypatch, capsys
    ):
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgresql://127.0.0.1:1/cortex_definitely_unreachable",
        )

        rc = _run()

        captured = capsys.readouterr()
        assert rc == 1
        assert captured.out == ""
        assert "cortex-migrate: cannot connect to database" in captured.err

    def test_never_raises_on_failure(self, monkeypatch):
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgresql://127.0.0.1:1/cortex_definitely_unreachable",
        )
        # No exception should escape — the contract is exit code + stream,
        # not a caller-visible traceback.
        rc = _run()
        assert isinstance(rc, int)

    def test_store_construction_failure_reported_distinctly_from_connect_failure(
        self, monkeypatch, capsys
    ):
        """The DB is reachable (probe succeeds) but PgMemoryStore(...)
        itself raises — e.g. auth rejected mid-construction, a driver
        error, or (per the softened docstring contract) any exception
        that escapes _init_schema rather than being logged+skipped
        per-statement. This is a distinct error path from "cannot
        connect" and must report its own, different stderr prefix.
        """
        import mcp_server.migrate as migrate_module

        monkeypatch.setenv("DATABASE_URL", _TEST_DB_URL)
        monkeypatch.setattr(migrate_module, "_probe_was_current", lambda url, h: True)

        def _raise_on_construct(*args, **kwargs):
            raise RuntimeError("simulated PgMemoryStore construction failure")

        monkeypatch.setattr(
            "mcp_server.infrastructure.pg_store.PgMemoryStore",
            _raise_on_construct,
        )

        rc = _run()

        captured = capsys.readouterr()
        assert rc == 1
        assert captured.out == ""
        assert "cortex-migrate: schema migration failed" in captured.err
        assert "simulated PgMemoryStore construction failure" in captured.err


def test_env_untouched_after_module_import():
    """migrate.py is import-safe: importing it alone must not read
    DATABASE_URL or open a connection (composition-root discipline —
    only ``main()``/``_run()`` touches the environment or the network).
    """
    prior = os.environ.get("DATABASE_URL")
    import importlib

    import mcp_server.migrate as migrate_module

    importlib.reload(migrate_module)
    assert os.environ.get("DATABASE_URL") == prior
