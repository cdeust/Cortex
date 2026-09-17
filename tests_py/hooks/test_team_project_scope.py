"""Real store and hook project isolation for team decisions. source: ADR-1083"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_server.handlers.forget import _get_store
from mcp_server.handlers.remember import handler
from mcp_server.hooks.agent_briefing_query import _fetch_agent_context
from mcp_server.hooks.session_start import _fetch_team_decisions


def _write(content, **kwargs):
    result = asyncio.run(handler({"content": content, "force": True, **kwargs}))
    assert result["stored"], result
    return result["memory_id"]


def _hook(module, cwd):
    env = os.environ.copy()
    env.pop("CLAUDE_PROJECT_ROOT", None)
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
        cwd=Path(__file__).resolve().parents[2],
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize("module", ["auto_recall", "session_start"])
def test_team_decision_hooks_remain_project_scoped(module):
    content = "Decision: retain the ledger dossier layout for ORCHID_SCOPE_MARKER"
    _write(content, agent_topic="engineer", directory="/tmp/project-a")
    assert "ORCHID_SCOPE_MARKER" in _hook(module, "/tmp/project-a")
    assert "ORCHID_SCOPE_MARKER" not in _hook(module, "/tmp/project-b")


@pytest.mark.parametrize("module", ["auto_recall", "session_start"])
def test_explicit_global_hooks_cross_projects(module):
    content = "Decision: retain the ledger dossier layout for GLOBAL_SCOPE_MARKER"
    _write(content, agent_topic="engineer", directory="/tmp/project-a", is_global=True)
    assert "GLOBAL_SCOPE_MARKER" in _hook(module, "/tmp/project-a")
    assert "GLOBAL_SCOPE_MARKER" in _hook(module, "/tmp/project-b")


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
