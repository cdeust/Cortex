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
    error = _refused(lambda: _write_scope.require_writable_domain("alpha", "t", env))
    assert str(error) == _refusal("t", session="")


def test_star_allows_every_project(projects):
    env = {
        _write_scope.SESSION_ENV: str(projects / "beta"),
        _write_scope.ALLOW_ENV: "*",
    }
    _write_scope.require_writable_domain("alpha", "remember", env)


# ── The exact refusal, its normalisation and the local allowance ────────────


def _refusal(tool, domain="alpha", session="beta"):
    where = f"this session's project ({session!r})" if session else "no known project"
    return (
        f"{tool}: domain {domain!r} belongs to another project than {where}; "
        f"set CORTEX_CROSS_PROJECT_WRITES={domain} (or '*') in the environment "
        "to allow it"
    )


def _refused(call):
    with pytest.raises(ValidationError) as caught:
        call()
    return caught.value


def test_the_refusal_names_the_tool_the_domain_and_the_session(projects):
    env = {_write_scope.SESSION_ENV: str(projects / "beta")}
    error = _refused(lambda: _write_scope.require_writable_domain(" ALPHA ", "t", env))
    assert str(error) == _refusal("t")
    assert error.details == {
        "tool": "t",
        "field": "domain",
        "domain": "alpha",
        "session": "beta",
    }


def test_no_domain_is_always_writable(projects):
    # Even next to a project named like a placeholder default.
    subprocess.run(["git", "init", "-q", str(projects / "xxxx")], check=True)
    domain_mapping._build_registry.cache_clear()
    env = {_write_scope.SESSION_ENV: str(projects / "beta")}
    _write_scope.require_writable_domain(None, "t", env)
    _write_scope.require_writable_domain("", "t", env)


@pytest.mark.parametrize("allow", ["Alpha", " beta , alpha ,", "alpha,beta"])
def test_the_allowance_is_a_trimmed_case_blind_list(projects, allow):
    env = {
        _write_scope.SESSION_ENV: str(projects / "beta"),
        _write_scope.ALLOW_ENV: allow,
    }
    _write_scope.require_writable_domain("alpha", "t", env)


def test_without_the_variable_no_project_is_allowed(projects):
    # A project named like any placeholder default stays refused too.
    subprocess.run(["git", "init", "-q", str(projects / "xxxx")], check=True)
    domain_mapping._build_registry.cache_clear()
    env = {_write_scope.SESSION_ENV: str(projects / "beta")}
    for name in ("alpha", "xxxx"):
        error = _refused(
            lambda n=name: _write_scope.require_writable_domain(n, "t", env)
        )
        assert str(error) == _refusal("t", name)


def test_the_session_is_the_working_directory_without_the_variable(
    projects, monkeypatch
):
    monkeypatch.chdir(projects / "beta")
    assert _write_scope.session_domain({}) == "beta"
    assert (
        _write_scope.session_domain({_write_scope.SESSION_ENV: str(projects / "alpha")})
        == "alpha"
    )


# ── Every writing tool applies it, under its own name ───────────────────────


@pytest.mark.asyncio
async def test_remember_refuses_under_its_name(projects):
    with pytest.raises(ValidationError) as caught:
        await remember_handler({"content": MARKER, "domain": "alpha", "force": True})
    assert str(caught.value) == _refusal("remember")


def test_seed_project_refuses_another_projects_directory(projects):
    from mcp_server.handlers import seed_project

    for args in ({"directory": str(projects / "alpha")}, {"domain": "alpha"}):
        error = _refused(lambda a=args: seed_project._parse_args(a))
        assert str(error) == _refusal("seed_project")


@pytest.mark.asyncio
async def test_ingest_prd_refuses_before_writing(projects, monkeypatch):
    from mcp_server.handlers import ingest_prd

    written = []
    monkeypatch.setattr(ingest_prd, "write_page", lambda *a, **k: written.append(a))
    with pytest.raises(ValidationError) as caught:
        await ingest_prd.handler(
            {"content": "# Plan\n\nA requirement.", "domain": "alpha"}
        )
    assert str(caught.value) == _refusal("ingest_prd")
    assert written == []


@pytest.mark.asyncio
async def test_ingest_document_refuses_before_writing(projects, tmp_path):
    from mcp_server.handlers import ingest_document

    page = tmp_path / "export.html"
    page.write_text("<h1>Onboarding</h1><p>welcome</p>", encoding="utf-8")
    with pytest.raises(ValidationError) as caught:
        await ingest_document.handler({"path": str(page), "domain": "alpha"})
    assert str(caught.value) == _refusal("ingest_document")
