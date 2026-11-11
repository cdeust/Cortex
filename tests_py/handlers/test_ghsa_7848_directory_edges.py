"""Edges of the directory rule found after the first fix (GHSA-7848-qh48-mx2w).

Codex on PR #977: a folder name may end with a space, and the hooks compare the
stored text as written; `seed_project` purged before `remember` refused the first
file. The mutation gate of PR #970: a row is judged in the environment the caller
passes, not in the process's.
"""

from __future__ import annotations

import subprocess

import pytest

from mcp_server.errors import ValidationError
from mcp_server.handlers import _write_scope
from mcp_server.shared import domain_mapping
from tests_py.handlers import test_ghsa_7848_cross_project_write as _base
from tests_py.handlers import test_ghsa_7848_resolved_domain as _resolved

projects = _base.projects  # alpha and beta under `dev`; the session runs in beta
family = _resolved.family  # the family `foo-lib`, whose name is an alias of `zed`
ALLOW = _write_scope.ALLOW_ENV


def _row(projects, where, **more):
    return {"id": 7, "domain": "code:alpha", "directory_context": str(where)} | more


def test_a_folder_name_that_ends_with_a_space_is_compared_as_written(projects):
    # Codex on PR #977: the hooks compare the stored text, they trim nothing.
    spaced = projects / "gamma "
    (spaced / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(spaced)], check=True)
    domain_mapping._build_registry.cache_clear()
    reached = _write_scope._reached_projects
    owner = reached(str(spaced))
    assert len(owner) == 1 and owner != {"alpha"} and owner != {"beta"}
    assert reached(str(spaced / "src")) == owner
    assert reached(str(projects / "gamma")) == frozenset()
    with pytest.raises(ValidationError, match=r"^t: a memory stored under"):
        _write_scope.require_writable_directory(str(spaced), "t")


@pytest.mark.asyncio
async def test_seed_project_refuses_a_folder_above_before_it_purges(
    projects, monkeypatch
):
    # Codex on PR #977: the purge ran, then remember refused the first file.
    from mcp_server.handlers import seed_project

    purged = []

    class Store:
        def delete_memories_by_tag(self, tag, domain=None):
            purged.append((tag, domain))
            return 0

    monkeypatch.setattr(seed_project, "is_transient_seed_root", lambda _path: False)
    monkeypatch.setattr(seed_project, "_get_store", lambda: Store())
    monkeypatch.setattr(seed_project, "collect_all_discoveries", lambda *a: [])
    with pytest.raises(ValidationError, match=r"^seed_project: a memory stored under"):
        await seed_project.handler({"directory": str(projects), "domain": "beta"})
    assert purged == []


def test_a_row_is_judged_in_the_environment_it_is_given(projects):
    # The caller's environment decides, not the process's: an allowance passed in
    # opens the row, and the process environment (no allowance) is not consulted.
    foreign = _row(projects, projects / "alpha", domain="team-notes")
    allowing = {_write_scope.SESSION_ENV: str(projects / "beta"), ALLOW: "alpha"}
    _write_scope.require_writable_memory(foreign, "anchor", allowing)
    assert _write_scope.memory_writable(foreign, allowing) is True
    with pytest.raises(ValidationError, match=r"^anchor: a memory stored under"):
        _write_scope.require_writable_memory(foreign, "anchor")


def test_a_worktree_entry_that_is_not_text_does_not_stop_the_check(projects):
    # git writes a path there; bytes that are no UTF-8 are still a path to the OS.
    entry = projects / "alpha" / ".git" / "worktrees" / "odd"
    entry.mkdir(parents=True)
    (entry / "gitdir").write_bytes(b"/tmp/caf\xe9/.git\n")
    (entry.parent / "a-folder" / "gitdir").mkdir(parents=True)  # unreadable: skipped
    (entry.parent / "empty").mkdir()
    (entry.parent / "empty" / "gitdir").write_bytes(b"\n")
    roots = domain_mapping.project_roots()
    assert roots[str(projects / "alpha")] == "alpha"
    assert roots["/tmp/caf\udce9"] == "alpha" and "." not in roots


def test_no_working_directory_resolves_to_no_domain(projects):
    assert domain_mapping.resolve_cwd("") == ""


@pytest.mark.asyncio
async def test_seed_project_refuses_a_domain_that_resolves_again_before_it_purges(
    family, tmp_path, monkeypatch
):
    # Review 1 of PR #977, B1: `foo-lib-b` resolves to the family `foo-lib`, which
    # remember resolved once more to `zed`: the purge ran, then the write was refused.
    from mcp_server.handlers import seed_project

    purged = []

    class Store:
        def delete_memories_by_tag(self, tag, domain=None):
            purged.append((tag, domain))
            return 0

    plain = tmp_path.resolve() / "plain"
    plain.mkdir()
    monkeypatch.setenv(_write_scope.SESSION_ENV, str(family / "foo-lib-a"))
    monkeypatch.setattr(seed_project, "is_transient_seed_root", lambda _path: False)
    monkeypatch.setattr(seed_project, "_get_store", lambda: Store())
    monkeypatch.setattr(seed_project, "collect_all_discoveries", lambda *a: [])
    with pytest.raises(ValidationError) as refused:
        await seed_project.handler({"directory": str(plain), "domain": "foo-lib-b"})
    assert str(refused.value) == (
        "seed_project: domain 'foo-lib' is also an alias of 'zed', the domain the "
        "files would be written under; run it from a directory inside the project"
    )
    assert refused.value.details == {
        "tool": "seed_project",
        "field": "domain",
        "domain": "zed",
    }
    assert purged == []
    # Inside the project the directory decides, and the seed goes through.
    await seed_project.handler({"directory": str(family / "foo-lib-a")})
    assert purged == [("seeded", "foo-lib")]
