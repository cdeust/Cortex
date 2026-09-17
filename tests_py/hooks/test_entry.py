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


def test_pyproject_declares_the_console_script() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert scripts["hypermnesia-mcp-hook"] == "mcp_server.hooks.entry:main"
