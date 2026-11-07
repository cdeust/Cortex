"""A session cannot write into another project's memory domain (GHSA-7848-qh48-mx2w).

The reported attack, reproduced here end to end on the real handlers and store:
two git repositories `alpha` and `beta` under an isolated CORTEX_DEV_ROOT, a
session in `beta`, and a `remember` call steered toward `alpha` either by a
`directory` inside `alpha` or by an unregistered directory plus `domain="alpha"`.
Before the fix both stored the marker under `alpha`, and alpha's
`query_methodology` hot memories served it. A local variable, never a tool
argument, may reopen such a write (owner decision 2026-11-07).
"""

from __future__ import annotations

import subprocess

import pytest

from mcp_server.errors import ValidationError
from mcp_server.handlers import _write_scope, query_methodology
from mcp_server.handlers.remember import handler as remember_handler
from mcp_server.shared import domain_mapping

MARKER = "GHSA-7848 harmless marker"


@pytest.fixture
def projects(tmp_path, monkeypatch):
    """`alpha` and `beta` git repositories; the session runs in `beta`."""
    dev = tmp_path.resolve() / "dev"  # macOS /var is a link to /private/var
    for name in ("alpha", "beta"):
        (dev / name / "src").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(dev / name)], check=True)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CORTEX_DEV_ROOT", str(dev))
    monkeypatch.setenv(_write_scope.SESSION_ENV, str(dev / "beta"))
    monkeypatch.delenv(_write_scope.ALLOW_ENV, raising=False)
    # tests_py/_domain_mapping_isolation.py stubs the scan to [] for the session.
    monkeypatch.setattr(domain_mapping, "_candidate_dev_roots", lambda: [dev])
    domain_mapping._build_registry.cache_clear()
    yield dev
    domain_mapping._build_registry.cache_clear()


def _alpha_context():
    return [m["content"] for m in query_methodology._get_hot_memories("alpha", "")]


@pytest.mark.asyncio
async def test_a_directory_inside_another_project_is_refused(projects):
    with pytest.raises(ValidationError, match="CORTEX_CROSS_PROJECT_WRITES=alpha"):
        await remember_handler(
            {
                "content": MARKER,
                "directory": str(projects / "alpha" / "src"),
                "force": True,
            }
        )
    assert MARKER not in _alpha_context()


@pytest.mark.asyncio
async def test_another_projects_domain_named_explicitly_is_refused(projects, tmp_path):
    with pytest.raises(ValidationError, match="belongs to another project"):
        await remember_handler(
            {
                "content": MARKER,
                "directory": str(tmp_path / "unregistered"),
                "domain": "alpha",
                "force": True,
            }
        )
    assert MARKER not in _alpha_context()


@pytest.mark.asyncio
async def test_the_sessions_own_project_and_shared_domains_stay_writable(projects):
    own = await remember_handler(
        {"content": "beta note", "directory": str(projects / "beta"), "force": True}
    )
    shared = await remember_handler(
        {"content": "team note", "domain": "team-notes", "force": True}
    )
    assert own["stored"] is True and shared["stored"] is True
    assert "beta note" not in _alpha_context()


@pytest.mark.asyncio
async def test_the_local_variable_reopens_the_named_project(projects, monkeypatch):
    monkeypatch.setenv(_write_scope.ALLOW_ENV, "alpha")
    stored = await remember_handler(
        {"content": MARKER, "domain": "alpha", "force": True}
    )
    assert stored["stored"] is True
    assert MARKER in _alpha_context()


def test_a_tool_argument_cannot_reopen_it(projects):
    # The rule reads only the environment: no argument of the call is consulted.
    with pytest.raises(ValidationError):
        _write_scope.require_writable_domain("alpha", "remember", {})


def test_a_session_outside_any_known_project_cannot_target_one(projects):
    env = {_write_scope.SESSION_ENV: str(projects.parent / "elsewhere")}
    with pytest.raises(ValidationError, match="no known project"):
        _write_scope.require_writable_domain("alpha", "remember", env)


def test_star_allows_every_project(projects):
    env = {
        _write_scope.SESSION_ENV: str(projects / "beta"),
        _write_scope.ALLOW_ENV: "*",
    }
    _write_scope.require_writable_domain("alpha", "remember", env)
