"""Tests for the console entry point that runs any Cortex lifecycle hook
from the installed wheel, without the repository or scripts/launcher.py.

Source: this PR's specification (Codex plugin wave, PR 1). A Codex plugin
ships only its own directory and calls
``uvx --from "hypermnesia-mcp[postgresql,sqlite]" hypermnesia-mcp-hook
<module>``, so the eleven hook modules the Claude Code plugin manifest
wires (.claude-plugin/plugin.json) must be runnable without
scripts/launcher.py.

Parity: mcp_server.hooks.entry must behave exactly like scripts/launcher.py
for every allowlisted module on a benign event, because both are meant to
run the same hook the same way -- the Codex plugin is not a second
implementation of hook dispatch, it is a second caller of the same one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# tomllib is 3.11+; requires-python is >=3.10 (pyproject.toml), so the
# fallback backport is used on 3.10, exactly like build/hatchling's own
# dependency on it (uv.lock: tomli, marker python_full_version < "3.11").
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_PATH = REPO_ROOT / "scripts" / "launcher.py"

HOOK_MODULES = (
    "session_start",
    "auto_recall",
    "decision_gate",
    "no_deps_gate",
    "post_tool_capture",
    "preemptive_context",
    "pipeline_impact_bump",
    "post_commit_reindex",
    "session_lifecycle",
    "compaction_checkpoint",
    "agent_briefing",
)


def _benign_event(tmp_path: Path) -> str:
    target = tmp_path / "seen.txt"
    target.write_text("hello\n", encoding="utf-8")
    return json.dumps(
        {
            "session_id": "t",
            "cwd": str(tmp_path),
            "tool_name": "Read",
            "tool_input": {"file_path": str(target)},
            "tool_response": "",
        }
    )


def _isolated_env(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    claude_dir = tmp_path / "claude-dir"
    claude_dir.mkdir(exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CORTEX_CLAUDE_DIR"] = str(claude_dir)
    env["CORTEX_MEMORY_STORE_BACKEND"] = "sqlite"
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    env.pop("DATABASE_URL", None)
    return env


@pytest.mark.parametrize("module", HOOK_MODULES)
def test_entry_matches_launcher_on_benign_event(module: str, tmp_path: Path) -> None:
    event = _benign_event(tmp_path)
    env = _isolated_env(tmp_path)

    via_entry = subprocess.run(
        [sys.executable, "-m", "mcp_server.hooks.entry", module],
        input=event,
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )
    via_launcher = subprocess.run(
        [sys.executable, str(LAUNCHER_PATH), f"mcp_server.hooks.{module}"],
        input=event,
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )

    assert via_entry.returncode == via_launcher.returncode, (
        via_entry.stderr,
        via_launcher.stderr,
    )
    assert via_entry.stdout == via_launcher.stdout


def test_entry_refuses_a_module_outside_the_allowlist(tmp_path: Path) -> None:
    env = _isolated_env(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcp_server.hooks.entry",
            "mcp_server.handlers.remember",
        ],
        input="",
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 2
    assert result.stdout == ""


def test_prepare_environment_marker_selects_sqlite_and_skips_database_url(
    tmp_path: Path,
) -> None:
    from mcp_server.hooks.entry import prepare_environment

    marker = tmp_path / "backend.json"
    marker.write_text(json.dumps({"backend": "sqlite"}), encoding="utf-8")
    environ: dict[str, str] = {}

    prepare_environment(environ, marker_path=marker)

    assert environ["CORTEX_MEMORY_STORE_BACKEND"] == "sqlite"
    assert "DATABASE_URL" not in environ


def test_prepare_environment_no_marker_postgresql_sets_default_database_url(
    tmp_path: Path,
) -> None:
    from mcp_server.hooks.entry import prepare_environment

    environ: dict[str, str] = {"CORTEX_MEMORY_STORE_BACKEND": "postgresql"}

    prepare_environment(environ, marker_path=tmp_path / "absent.json")

    assert environ["DATABASE_URL"] == "postgresql://localhost:5432/cortex"


@pytest.fixture
def codex_auto_store(tmp_path: Path, monkeypatch):
    from mcp_server.hooks.entry import prepare_environment, resolve_auto_backend
    from mcp_server.infrastructure.backend_marker import effective_backend
    from mcp_server.infrastructure.memory_config import get_memory_settings
    from mcp_server.infrastructure import memory_store
    from mcp_server.infrastructure.memory_store import (
        get_shared_store,
        reset_shared_store,
    )
    from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

    root = tmp_path / "claude"
    monkeypatch.setenv("CORTEX_RUNTIME", "cowork")
    monkeypatch.setenv("CORTEX_CLAUDE_DIR", str(root))
    monkeypatch.setenv(
        "CORTEX_MEMORY_SQLITE_FALLBACK_PATH", str(tmp_path / "memory.db")
    )
    monkeypatch.delenv("CORTEX_MEMORY_STORE_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CORTEX_MEMORY_DATABASE_URL", raising=False)
    monkeypatch.setattr(memory_store, "_try_pg_verbose", lambda _url: (None, "offline"))
    reset_shared_store()
    get_memory_settings.cache_clear()
    try:
        # The resolver writes os.environ directly; preserve the absent key that
        # monkeypatch.delenv established, including on PostgreSQL-backed CI.
        with patch.dict(os.environ):
            prepare_environment(os.environ, root / "methodology" / "backend.json")
            resolve_auto_backend(os.environ)
            store = get_shared_store()
            assert isinstance(store, SqliteMemoryStore)
            assert (
                effective_backend(os.environ, root / "methodology" / "backend.json")
                == "sqlite"
            )
            assert "DATABASE_URL" not in os.environ
            yield store
    finally:
        assert "CORTEX_MEMORY_STORE_BACKEND" not in os.environ
        reset_shared_store()
        get_memory_settings.cache_clear()


def test_codex_auto_hook_uses_actual_sqlite_store_without_marker(
    codex_auto_store, capsys
) -> None:
    from mcp_server.hooks import agent_briefing

    codex_auto_store.insert_memory(
        {
            "content": "shared Codex decision",
            "agent_context": "worker",
            "directory_context": "/project",
            "heat": 0.9,
            "heat_base": 0.9,
            "is_team_decision": True,
        }
    )
    with pytest.raises(SystemExit):
        agent_briefing.process_event(
            {
                "hook_event_name": "SubagentStart",
                "agent_type": "worker",
                "cwd": "/project",
                "session_id": "fresh-codex",
            }
        )
    assert "shared Codex decision" in capsys.readouterr().out


def test_codex_auto_hook_keeps_postgres_when_store_selects_it(
    tmp_path: Path, monkeypatch
) -> None:
    from mcp_server.hooks.entry import prepare_environment, resolve_auto_backend
    from mcp_server.infrastructure import memory_store

    monkeypatch.setattr(memory_store, "get_shared_store", lambda: object())
    environ = {"CORTEX_RUNTIME": "cowork"}
    prepare_environment(environ, tmp_path / "absent.json")
    resolve_auto_backend(environ)
    assert environ["CORTEX_MEMORY_STORE_BACKEND"] == "postgresql"
    assert environ["DATABASE_URL"] == "postgresql://127.0.0.1:5432/cortex"


def test_codex_explicit_database_url_stays_explicit(
    tmp_path: Path, monkeypatch
) -> None:
    from mcp_server.hooks.entry import prepare_environment, resolve_auto_backend
    from mcp_server.infrastructure import memory_store

    def unexpected_store():
        pytest.fail("explicit PostgreSQL URL must not trigger auto selection")

    monkeypatch.setattr(memory_store, "get_shared_store", unexpected_store)
    environ = {
        "CORTEX_RUNTIME": "cowork",
        "DATABASE_URL": "postgresql:///operator_db",
    }
    prepare_environment(environ, tmp_path / "absent.json")
    resolve_auto_backend(environ)
    assert environ["DATABASE_URL"] == "postgresql:///operator_db"
    assert "CORTEX_MEMORY_STORE_BACKEND" not in environ


def test_packaged_codex_entry_selects_sqlite_before_hook_wiring(
    tmp_path: Path,
) -> None:
    """Exercise the real console path with neither runtime nor backend supplied."""
    env = _isolated_env(tmp_path)
    env.pop("CORTEX_RUNTIME", None)
    env.pop("CORTEX_MEMORY_STORE_BACKEND", None)
    env.pop("CORTEX_MEMORY_DATABASE_URL", None)
    db = tmp_path / "codex-memory.db"
    env["CORTEX_MEMORY_SQLITE_FALLBACK_PATH"] = str(db)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import mcp_server.infrastructure.memory_store as store; "
                "store._try_pg_verbose = lambda _url: (None, 'offline'); "
                "from mcp_server.hooks.entry import main; main()"
            ),
            "decision_gate",
        ],
        input=json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Read"}),
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert db.is_file()


def test_pyproject_declares_the_console_script() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert scripts["hypermnesia-mcp-hook"] == "mcp_server.hooks.entry:main"
