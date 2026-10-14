"""scripts/launcher.py ``_apply_backend``: one backend for the server and hooks.

Measured on main (2026-10-14, isolated HOME, no marker): the launcher set
``DATABASE_URL=postgresql://localhost:5432/cortex`` for every process, so a
fresh install's MCP server wrote into whatever PostgreSQL listened there.
Claude Code passes the user's ``database_url`` to the server as
``DATABASE_URL`` and to hooks only as ``CLAUDE_PLUGIN_OPTION_DATABASE_URL``.

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
_PROBE = """
import json, os, sys
sys.path.insert(0, sys.argv[1])
import launcher
launcher._set_import_paths(sys.argv[2], sys.argv[3])
launcher._apply_backend()
print(json.dumps({k: os.environ.get(k) for k in
    ("CORTEX_MEMORY_STORE_BACKEND", "DATABASE_URL")}))
"""
_CLEARED = (
    "DATABASE_URL",
    "CORTEX_MEMORY_DATABASE_URL",
    "CORTEX_MEMORY_STORE_BACKEND",
    "CORTEX_BACKEND",
    "CLAUDE_PLUGIN_OPTION_DATABASE_URL",
    "CORTEX_CLAUDE_DIR",
)


def _resolve(tmp_path: Path, marker: dict | None = None, **env: str) -> dict:
    home = tmp_path / "home"
    if marker is not None:
        (home / ".claude" / "methodology").mkdir(parents=True)
        (home / ".claude" / "methodology" / "backend.json").write_text(
            json.dumps(marker)
        )
    child = {k: v for k, v in os.environ.items() if k not in _CLEARED}
    child.update(HOME=str(home), **env)
    done = subprocess.run(
        [sys.executable, "-c", _PROBE, str(REPO_ROOT / "scripts"), str(REPO_ROOT),
         str(tmp_path / "deps")],
        capture_output=True, text=True, env=child, check=True,
    )  # fmt: skip
    return json.loads(done.stdout)


def test_nothing_configured_is_the_sqlite_store_and_no_url(tmp_path):
    assert _resolve(tmp_path, DATABASE_URL="") == {
        "CORTEX_MEMORY_STORE_BACKEND": "sqlite",
        "DATABASE_URL": None,
    }


def test_the_hook_reads_the_option_the_server_gets_as_database_url(tmp_path):
    url = "postgresql://db.example:5432/cortex"
    resolved = _resolve(tmp_path, CLAUDE_PLUGIN_OPTION_DATABASE_URL=url)
    assert resolved["DATABASE_URL"] == url
    assert resolved["CORTEX_MEMORY_STORE_BACKEND"] != "sqlite"


def test_the_server_keeps_its_configured_url(tmp_path):
    url = "postgresql://db.example:5432/cortex"
    assert _resolve(tmp_path, DATABASE_URL=url)["DATABASE_URL"] == url


@pytest.mark.parametrize("url", ["", None])
def test_a_postgresql_marker_keeps_the_local_default(tmp_path, url):
    env = {} if url is None else {"DATABASE_URL": url}
    assert _resolve(tmp_path, {"backend": "postgresql"}, **env) == {
        "CORTEX_MEMORY_STORE_BACKEND": "postgresql",
        "DATABASE_URL": "postgresql://localhost:5432/cortex",
    }


def test_an_invalid_marker_does_not_stop_a_configured_url(tmp_path):
    """Review of #749: the marker is not read when the URL decides."""
    url = "postgresql://db.example:5432/cortex"
    resolved = _resolve(tmp_path, {"backend": "postgres"}, DATABASE_URL=url)
    assert resolved["DATABASE_URL"] == url
    assert resolved["CORTEX_MEMORY_STORE_BACKEND"] != "sqlite"


def test_an_invalid_marker_alone_is_cortex_not_ready(tmp_path):
    with pytest.raises(subprocess.CalledProcessError) as stopped:
        _resolve(tmp_path, {"backend": "postgres"})
    assert "Cortex not ready: backend marker" in stopped.value.stderr


def _marker(tmp_path: Path) -> dict | None:
    path = tmp_path / "home" / ".claude" / "methodology" / "backend.json"
    return json.loads(path.read_text()) if path.exists() else None


def test_a_fresh_home_records_the_sqlite_choice_once(tmp_path):
    """Review of #749: the first launch persists its decision as the marker."""
    _resolve(tmp_path)
    assert _marker(tmp_path)["backend"] == "sqlite"
    assert _resolve(tmp_path)["CORTEX_MEMORY_STORE_BACKEND"] == "sqlite"


def test_a_configured_url_writes_no_marker(tmp_path):
    _resolve(tmp_path, DATABASE_URL="postgresql://db.example:5432/cortex")
    assert _marker(tmp_path) is None
