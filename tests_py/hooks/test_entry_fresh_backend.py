"""Issues #703/#704: choose SQLite before a hook can construct an auto store."""

import json

import pytest

from mcp_server.hooks import entry
from mcp_server.hooks.entry import prepare_environment
from mcp_server.infrastructure.backend_marker import BackendMarkerError
from mcp_server.infrastructure.managed_pg import ManagedPgError


def test_fresh_hook_environment_persists_sqlite_without_a_database_url(tmp_path):
    marker = tmp_path / "methodology" / "backend.json"
    env = {"CORTEX_RUNTIME": "cowork"}
    prepare_environment(env, marker)
    assert env.get("CORTEX_MEMORY_STORE_BACKEND") == "sqlite"
    assert "DATABASE_URL" not in env
    assert json.loads(marker.read_text())["backend"] == "sqlite"


@pytest.mark.parametrize("error", [BackendMarkerError, ManagedPgError, OSError])
def test_hook_startup_reports_resolution_failure_once(error, monkeypatch, capsys):
    def fail(environ):
        raise error("cannot resolve storage")

    monkeypatch.setattr(entry, "prepare_environment", fail)
    with pytest.raises(SystemExit) as stopped:
        entry._prepare_or_exit({})
    assert stopped.value.code == 1
    assert capsys.readouterr().err == (
        "[cortex-hook] Cortex not ready: cannot resolve storage\n"
    )


def test_pg_helpers_do_nothing_without_a_resolved_url(monkeypatch):
    from mcp_server.hooks import auto_recall, session_start_db
    from mcp_server.infrastructure import db_connect

    def forbidden(*args, **kwargs):
        pytest.fail("an unconfigured hook must not connect or run PostgreSQL setup")

    monkeypatch.setattr(auto_recall, "_DATABASE_URL", "")
    monkeypatch.setattr(session_start_db, "_DATABASE_URL", "")
    monkeypatch.setattr(db_connect, "pg_connect", forbidden)
    monkeypatch.setattr(session_start_db.subprocess, "run", forbidden)
    assert auto_recall._connect() is None
    assert session_start_db._connect_pg() is None
    assert session_start_db._try_setup_db() is None
