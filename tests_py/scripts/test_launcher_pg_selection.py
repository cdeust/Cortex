"""Which store a launch and Setup choose once a managed server exists (ADR-1114).

PR #748's review (2026-10-16, blocker 3): with ``database_url`` set, hooks
(which receive it only as ``CLAUDE_PLUGIN_OPTION_DATABASE_URL``) started the
managed server while the MCP server used the user's database: two stores.
A configured database must always win, in every hook, the server and Setup.

source: ADR-1114
source: ADR-1104
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_OPTION_URL = "postgresql://db.example:5432/cortex"  # source: test fixture value
_PROBE = """
import json, os, sys
sys.path.insert(0, sys.argv[1])
import launcher
launcher._set_import_paths(sys.argv[2], sys.argv[3])
import launcher_backend
launcher_backend.apply()
print(json.dumps({k: os.environ.get(k) for k in
    ("CORTEX_MEMORY_STORE_BACKEND", "DATABASE_URL", "CORTEX_MANAGED_PG_ROOT")}))
"""
_CLEARED = (
    "DATABASE_URL",
    "CORTEX_MEMORY_DATABASE_URL",
    "CORTEX_MEMORY_STORE_BACKEND",
    "CORTEX_BACKEND",
    "CLAUDE_PLUGIN_OPTION_DATABASE_URL",
    "CORTEX_CLAUDE_DIR",
    "CORTEX_MEMORY_DB_PATH",
    "CORTEX_MEMORY_SQLITE_FALLBACK_PATH",
    "CORTEX_MANAGED_PG_ROOT",
)


def _marker(home: Path, record: dict) -> Path:
    path = home / ".claude" / "methodology" / "backend.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    return path


def _launch(tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    child = {k: v for k, v in os.environ.items() if k not in _CLEARED}
    child.update(HOME=str(tmp_path / "home"), **env)
    return subprocess.run(
        [sys.executable, "-c", _PROBE, str(REPO_ROOT / "scripts"), str(REPO_ROOT),
         str(tmp_path / "deps")],
        capture_output=True, text=True, env=child, check=False,
    )  # fmt: skip


def _managed_marker(tmp_path: Path) -> Path:
    root = tmp_path / "data" / "pg"
    root.mkdir(parents=True)
    _marker(
        tmp_path / "home", {"backend": "managed", "root": str(root), "written_by": "t"}
    )
    return root


@pytest.mark.skipif(os.name == "nt", reason="the managed server is POSIX only")
def test_the_hook_option_wins_over_a_managed_marker_and_starts_nothing(tmp_path):
    root = _managed_marker(tmp_path)
    done = _launch(tmp_path, CLAUDE_PLUGIN_OPTION_DATABASE_URL=_OPTION_URL)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {
        "CORTEX_MEMORY_STORE_BACKEND": None,
        "DATABASE_URL": _OPTION_URL,
        "CORTEX_MANAGED_PG_ROOT": None,
    }
    assert sorted(p.name for p in root.iterdir()) == []  # no lock, no supervisor


@pytest.mark.skipif(os.name == "nt", reason="the managed server is POSIX only")
def test_a_managed_marker_whose_server_cannot_start_stops_the_launch_loudly(tmp_path):
    root = _managed_marker(tmp_path)  # no installed.json: nothing to start
    done = _launch(tmp_path)
    assert done.returncode == 1
    assert "Cortex not ready" in done.stderr and "claude --init-only" in done.stderr
    assert json.loads((root / "status.json").read_text())["state"] == "failed"


def test_a_managed_marker_without_root_is_an_error_naming_the_file(tmp_path):
    marker = _marker(tmp_path / "home", {"backend": "managed"})
    done = _launch(tmp_path)
    assert done.returncode == 1
    assert str(marker) in done.stderr


@pytest.fixture
def select(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT / "scripts"))
    from mcp_server.infrastructure import backend_resolution
    import launcher_pg_select

    return launcher_pg_select, backend_resolution


def _eligible(select, tmp_path, marker=None, files=(), **env):
    pick, _backend = select
    methodology = tmp_path / "methodology"
    methodology.mkdir(exist_ok=True)
    for name in files:
        (methodology / name).write_text("x")
    environ = {"HOME": str(tmp_path), **env}
    return pick.why_not_eligible(environ, marker, methodology / "backend.json")


def test_a_fresh_install_is_eligible(select, tmp_path):
    assert _eligible(select, tmp_path) == ""


def test_setup_with_the_hook_option_is_not_eligible(select, tmp_path):
    why = _eligible(select, tmp_path, CLAUDE_PLUGIN_OPTION_DATABASE_URL=_OPTION_URL)
    assert "database_url" in why


def test_the_launchers_own_sqlite_marker_without_a_store_stays_eligible(
    select, tmp_path
):
    marker = {"backend": "sqlite", "written_by": select[1].WRITTEN_BY}
    assert _eligible(select, tmp_path, marker) == ""


def test_an_existing_sqlite_store_is_never_switched(select, tmp_path):
    marker = {"backend": "sqlite", "written_by": select[1].WRITTEN_BY}
    why = _eligible(select, tmp_path, marker, files=("memory.db",))
    assert "SQLite store exists" in why


def test_a_store_moved_by_cortex_memory_db_path_is_seen(select, tmp_path):
    moved = tmp_path / "elsewhere.db"
    moved.write_text("x")
    marker = {"backend": "sqlite", "written_by": select[1].WRITTEN_BY}
    why = _eligible(select, tmp_path, marker, CORTEX_MEMORY_DB_PATH=str(moved))
    assert str(moved) in why


@pytest.mark.parametrize(
    "marker",
    [
        {"backend": "postgresql", "written_by": "launcher (first launch, ADR-1104)"},
        {"backend": "sqlite", "written_by": "install-plugin.sh"},
    ],
)
def test_a_marker_someone_chose_is_kept(select, tmp_path, marker):
    assert "selects" in _eligible(select, tmp_path, marker)


def test_earlier_cortex_state_without_a_marker_is_not_eligible(select, tmp_path):
    assert "earlier Cortex state" in _eligible(
        select, tmp_path, files=("profiles.json",)
    )


def test_the_pure_resolution_names_postgresql_for_a_managed_marker():
    # D1: no longer an error outside the launcher; attaching is
    # apply_backend_resolution's job (tests_py/infrastructure/test_managed_pg_attach).
    from mcp_server.infrastructure.backend_marker import resolve_backend_env

    marker = {"backend": "managed", "root": "/r"}
    assert resolve_backend_env({}, marker, default="sqlite") == {
        "CORTEX_MEMORY_STORE_BACKEND": "postgresql"
    }


def test_the_managed_root_is_not_earlier_cortex_state(select, tmp_path):
    # D5: Setup creates methodology/managed-pg before it may select the store.
    (tmp_path / "methodology" / "managed-pg").mkdir(parents=True)
    assert _eligible(select, tmp_path) == ""


def test_a_managed_marker_is_written_only_with_its_root(tmp_path):
    from mcp_server.infrastructure.backend_marker import (
        BackendMarkerError,
        read_backend_marker,
        write_backend_marker,
    )

    path = tmp_path / "backend.json"
    with pytest.raises(BackendMarkerError):
        write_backend_marker("managed", "t", path)
    write_backend_marker("managed", "t", path, root="/data/pg")
    assert read_backend_marker(path)["root"] == "/data/pg"
