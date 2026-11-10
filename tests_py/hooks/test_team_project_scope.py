"""Real store and hook project isolation for team decisions. source: ADR-1083"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

import pytest

from mcp_server.handlers.forget import _get_store
from mcp_server.handlers.remember import handler
from mcp_server.hooks.agent_briefing_query import _fetch_agent_context
from mcp_server.hooks.agent_briefing_role import _pg_role_rows
from mcp_server.hooks.auto_recall import _recall_memories
from mcp_server.hooks.session_start_fetch import _fetch_team_decisions
from tests_py._hermetic_hook_env import hermetic_hook_env


def _write(content, **kwargs):
    result = asyncio.run(handler({"content": content, "force": True, **kwargs}))
    assert result["stored"], result
    return result["memory_id"]


def _hook(module, cwd, tmp_path):
    base = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_ROOT"}
    env, project = hermetic_hook_env(base, tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", f"mcp_server.hooks.{module}"],
        input=json.dumps(
            {
                "cwd": cwd,
                "prompt": "ledger dossier layout decision",
                "source": "startup",
            }
        ),
        capture_output=True,
        text=True,
        env=env,
        cwd=project,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("module", ["auto_recall", "session_start"])
def test_team_decision_hooks_remain_project_scoped(module, tmp_path):
    content = "Decision: retain the ledger dossier layout for ORCHID_SCOPE_MARKER"
    _write(content, agent_topic="engineer", directory="/tmp/project-a")
    assert "ORCHID_SCOPE_MARKER" in _hook(module, "/tmp/project-a", tmp_path)
    assert "ORCHID_SCOPE_MARKER" not in _hook(module, "/tmp/project-b", tmp_path)


@pytest.mark.parametrize("module", ["auto_recall", "session_start"])
def test_explicit_global_hooks_cross_projects(module, tmp_path, monkeypatch):
    # GHSA-7848-qh48-mx2w: a global write needs the allowance.
    monkeypatch.setenv("CORTEX_CROSS_PROJECT_WRITES", "*")
    content = "Decision: retain the ledger dossier layout for GLOBAL_SCOPE_MARKER"
    _write(content, agent_topic="engineer", directory="/tmp/project-a", is_global=True)
    assert "GLOBAL_SCOPE_MARKER" in _hook(module, "/tmp/project-a", tmp_path)
    assert "GLOBAL_SCOPE_MARKER" in _hook(module, "/tmp/project-b", tmp_path)


def test_pg_team_readers_scope_both_agent_passes():
    store = _get_store()
    if type(store).__name__ != "PgMemoryStore":
        pytest.skip("PostgreSQL backend required for raw PG hook queries")
    own = _write(
        "Decision: retain ledger dossier for local orchid",
        agent_topic="dba",
        directory="/tmp/project-a",
    )
    foreign = _write(
        "Decision: retain ledger dossier for foreign orchid",
        agent_topic="engineer",
        directory="/tmp/project-b",
    )
    conn = store._conn
    team_ids = {r["id"] for r in _fetch_team_decisions(conn, set(), "/tmp/project-a")}
    assert own in team_ids and foreign not in team_ids
    briefing_ids = {
        r["id"]
        for r in _fetch_agent_context(conn, "engineer", ["ledger"], "/tmp/project-a")
    }
    assert own in briefing_ids and foreign not in briefing_ids
    assert not _fetch_team_decisions(conn, set(), None)


def test_pg_briefing_passes_scope_a_windows_directory():
    """Issue #692: both briefing passes, the role priors and auto-recall match
    a row stored with Windows separators, as memory_matches_project does
    (ADR-1080). Called in process, so mutation testing reaches the queries."""
    store = _get_store()
    if type(store).__name__ != "PgMemoryStore":
        pytest.skip("PostgreSQL backend required for raw PG hook queries")
    root = "C:\\work\\orchid"
    prior = _write(
        "Engineer prior: keep the ledger orchid index warm",
        agent_topic="engineer",
        directory=root,
    )
    decision = _write(
        "Decision: retain the ledger orchid layout",
        agent_topic="dba",
        directory=root + "\\",
    )
    foreign = _write(
        "Engineer prior: keep the ledger orchid cache cold",
        agent_topic="engineer",
        directory="C:\\work\\other",
    )
    conn = store._conn
    sources = {
        r["id"]: r["source"]
        for r in _fetch_agent_context(conn, "engineer", ["ledger"], root)
    }
    assert sources.get(prior) == "agent-prior"
    assert sources.get(decision) == "team:dba"
    assert foreign not in sources
    role_ids = {r["id"] for r in _pg_role_rows(conn, "engineer", root, 5)}
    assert prior in role_ids
    assert decision not in role_ids and foreign not in role_ids
    recalled = {r["id"] for r in _recall_memories(conn, "ledger orchid", root)}
    assert prior in recalled and decision in recalled
    assert foreign not in recalled
