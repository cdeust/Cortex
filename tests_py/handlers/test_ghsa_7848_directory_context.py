"""The directory a write stores reaches no other project (GHSA-7848-qh48-mx2w).

Review 1 of PR #970: the scope check read `domain` only. The SessionStart and
auto-recall hooks select by `directory_context`: a memory is served to a session
whose project root is that directory or lies below it. A `directory` above another
project, with no domain or a shared one, passed the check and reached every project
under that folder; `ingest_prd(content=...)` stored under the folder above the
server's working directory; and a row carrying a shared domain with another
project's directory could be anchored, superseded or merged into.
"""

from __future__ import annotations

import pytest

from mcp_server.errors import ValidationError
from mcp_server.handlers import _write_scope, anchor
from mcp_server.handlers.remember import handler as remember_handler
from mcp_server.shared import domain_mapping
from mcp_server.shared.project_scope import memory_matches_project
from tests_py.handlers import test_ghsa_7848_cross_project_write as _base

projects = _base.projects  # alpha and beta under `dev`; the session runs in beta
MARKER = "GHSA-7848 directory marker"
ALLOW = _write_scope.ALLOW_ENV


@pytest.mark.asyncio
@pytest.mark.parametrize("domain", ["", "team-notes"])
async def test_a_folder_above_another_project_is_refused(projects, domain):
    above = str(projects)
    # The hooks' rule: alpha's session would be served a memory stored there.
    assert memory_matches_project(above, False, str(projects / "alpha"))
    with pytest.raises(ValidationError, match=r"served to project 'alpha'"):
        await remember_handler(
            {"content": MARKER, "directory": above, "domain": domain, "force": True}
        )


@pytest.mark.asyncio
async def test_the_sessions_own_tree_stays_writable(projects, tmp_path):
    for directory in (projects / "beta", projects / "beta" / "src", tmp_path / "x"):
        stored = await remember_handler(
            {"content": f"note {directory.name}", "directory": str(directory)}
            | {"force": True}
        )
        assert stored["stored"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("allowance", ["alpha", "*"])
async def test_the_local_variable_reopens_the_folder(projects, monkeypatch, allowance):
    monkeypatch.setenv(ALLOW, allowance)
    stored = await remember_handler(
        {"content": MARKER, "directory": str(projects), "force": True}
    )
    assert stored["stored"] is True


def test_which_projects_a_directory_reaches(projects):
    reached = _write_scope._reached_projects
    assert reached(str(projects)) == {"alpha", "beta"}
    assert reached(str(projects) + "/") == {"alpha", "beta"}
    assert reached("/") == {"alpha", "beta"}
    assert reached(str(projects / "alpha" / "src")) == {"alpha"}
    assert reached(str(projects / "beta")) == {"beta"}
    # A name that only starts like a root is another folder.
    assert reached(str(projects / "alph")) == frozenset()
    assert reached(f"  {projects}  ") == {"alpha", "beta"}
    link = projects.parent / "link"
    link.symlink_to(projects, target_is_directory=True)
    assert reached(str(link)) == {"alpha", "beta"}


def test_a_symlinked_parent_of_the_projects_is_compared_on_both_sides(
    projects, monkeypatch
):
    # Codex on PR #970: the discovery keeps the text of a symlinked parent
    # (`~/code -> /mnt/repos`), and the hooks compare path text.
    link = projects.parent / "code"
    link.symlink_to(projects, target_is_directory=True)
    monkeypatch.setattr(domain_mapping, "_candidate_dev_roots", lambda: [link])
    domain_mapping._build_registry.cache_clear()
    reached = _write_scope._reached_projects
    assert domain_mapping.resolve_cwd(str(link / "alpha")) == ""  # no help from it
    for parent in (link, projects):
        assert reached(str(parent)) == {"alpha", "beta"}
        assert reached(str(parent / "alpha")) == {"alpha"}
        assert reached(str(parent / "alpha" / "src")) == {"alpha"}
        assert reached(str(parent / "alphabet")) == frozenset()
    assert reached(str(projects.parent / "downloads")) == frozenset()


def test_a_relative_directory_or_a_label_reaches_no_session(projects, monkeypatch):
    # The hooks compare the stored text with absolute roots.
    monkeypatch.chdir(projects / "alpha")
    reached = _write_scope._reached_projects
    assert reached("src") == reached("run:42") == reached("") == frozenset()
    assert reached(None) == frozenset()


def test_the_refusal_names_the_project_and_the_session(projects, monkeypatch):
    with pytest.raises(ValidationError) as beta:
        _write_scope.require_writable_directory(str(projects), "remember")
    assert "another project than this session's project ('beta')" in str(beta.value)
    assert beta.value.details == {
        "tool": "remember",
        "field": "directory",
        "domain": "alpha",
        "session": "beta",
    }
    monkeypatch.setenv(_write_scope.SESSION_ENV, str(projects.parent / "elsewhere"))
    with pytest.raises(ValidationError) as nowhere:
        _write_scope.require_writable_directory(str(projects), "remember")
    assert "served to project 'alpha', another project than no known project" in str(
        nowhere.value
    )
    assert f"set {ALLOW}=alpha (or '*') in the environment" in str(nowhere.value)


def test_session_directory_is_the_open_project_else_the_working_directory(
    projects, monkeypatch
):
    assert _write_scope.session_directory() == str(projects / "beta")
    monkeypatch.delenv(_write_scope.SESSION_ENV)
    monkeypatch.chdir(projects / "alpha")
    assert _write_scope.session_directory() == str(projects / "alpha")


class _Rows:
    def __init__(self):
        self.rows = []

    def insert_memory(self, record):
        self.rows.append(record)
        return len(self.rows)


PRD = "# Plan\n\n## Decisions\n\n- keep the queue durable\n"


@pytest.fixture
def prd(monkeypatch):
    from mcp_server.handlers import ingest_prd

    store = _Rows()
    monkeypatch.setattr(ingest_prd, "write_page", lambda *a, **k: None)
    monkeypatch.setattr(ingest_prd, "_get_store", lambda: store)
    return ingest_prd, store


@pytest.mark.asyncio
async def test_prd_text_is_stored_under_the_sessions_project(projects, prd):
    ingest_prd, store = prd
    await ingest_prd.handler({"content": PRD})
    assert store.rows
    assert {r["directory_context"] for r in store.rows} == {str(projects / "beta")}


@pytest.mark.asyncio
@pytest.mark.parametrize("place", ["alpha/src", "."])
async def test_a_prd_file_in_or_above_another_project_is_refused(projects, prd, place):
    ingest_prd, store = prd
    page = projects / place / "plan.md"
    page.write_text(PRD, encoding="utf-8")
    with pytest.raises(ValidationError, match=r"^ingest_prd: a memory stored under"):
        await ingest_prd.handler({"path": str(page)})
    assert store.rows == []


@pytest.mark.asyncio
async def test_a_document_in_another_project_is_refused(projects, monkeypatch):
    from mcp_server.handlers import ingest_document

    async def persist(*_):
        raise AssertionError("refused before anything is written")

    monkeypatch.setattr(ingest_document, "_persist", persist)
    page = projects / "alpha" / "export.html"
    page.write_text("<h1>Onboarding</h1><p>welcome</p>", encoding="utf-8")
    with pytest.raises(ValidationError, match=r"^ingest_document: a memory stored"):
        await ingest_document.handler({"path": str(page)})


def _row(projects, where, **more):
    return {"id": 7, "domain": "code:alpha", "directory_context": str(where)} | more


def test_a_row_in_another_projects_directory_is_not_writable(projects):
    foreign = _row(projects, projects / "alpha")
    assert _write_scope.memory_writable(foreign) is False
    with pytest.raises(ValidationError, match=r"^anchor: a memory stored under"):
        _write_scope.require_writable_memory(foreign, "anchor")
    own = _row(projects, projects / "beta")
    assert _write_scope.memory_writable(own) is True
    _write_scope.require_writable_memory(own, "anchor")
    assert _write_scope.memory_writable(_row(projects, "")) is True


@pytest.mark.asyncio
async def test_anchor_refuses_a_shared_domain_row_of_another_project(
    projects, monkeypatch
):
    foreign = _row(projects, projects / "alpha", content="graph", tags=[], heat=0.5)

    class Store:
        def get_memory(self, _):
            return foreign

        def __getattr__(self, name):
            raise AssertionError(f"store.{name} called on a refused anchor")

    monkeypatch.setattr(anchor, "_get_store", lambda: Store())
    with pytest.raises(ValidationError, match=r"^anchor: a memory stored under"):
        await anchor.handler({"memory_id": 7, "reason": MARKER})
