"""No write reaches another project through global scope or an existing row.

GHSA-7848-qh48-mx2w, reviews 1-3 of #940: hot memories of a project are
`domain = ? OR is_global`, so a global write, or a change to a global memory or
to another project's row, reaches that project as well. Each path is driven on
the real handlers and store, from a session in `beta`, and the planted marker
must stay out of alpha's `query_methodology` hot memories.
"""

from __future__ import annotations

import pytest

from mcp_server.errors import ValidationError
from mcp_server.handlers import _write_scope, anchor, query_methodology, seed_project
from mcp_server.handlers.remember import handler as remember_handler
from mcp_server.handlers.remember_helpers import try_block_replica_upsert
from tests_py.handlers import test_ghsa_7848_cross_project_write as _base

# The two git repositories and the session in beta, shared with the base tests.
projects = _base.projects
MARKER = "GHSA-7848 global marker"
ALLOW = _write_scope.ALLOW_ENV


def _alpha_context():
    return [m["content"] for m in query_methodology._get_hot_memories("alpha", "")]


async def _alpha_memory(monkeypatch, content="alpha's own note"):
    """A memory in alpha's domain, written with the user's allowance."""
    monkeypatch.setenv(ALLOW, "alpha")
    stored = await remember_handler(
        {"content": content, "domain": "alpha", "force": True}
    )
    monkeypatch.delenv(ALLOW)
    return stored["memory_id"]


@pytest.mark.asyncio
async def test_an_explicit_global_write_is_refused(projects):
    with pytest.raises(ValidationError) as caught:
        await remember_handler({"content": MARKER, "is_global": True, "force": True})
    assert str(caught.value) == (
        "remember: is_global=true writes into every project's memory; "
        f"set {ALLOW}=* in the environment to allow it"
    )
    assert MARKER not in _alpha_context()


@pytest.mark.asyncio
async def test_a_detected_global_scope_stays_local_and_says_so(projects):
    stored = await remember_handler(
        {"content": f"Always use tabs in every project. {MARKER}", "force": True}
    )
    assert stored["stored"] is True
    assert (stored["is_global"], stored["global_reason"]) == (
        False,
        _write_scope.KEPT_LOCAL,
    )
    assert not any(MARKER in c for c in _alpha_context())


@pytest.mark.asyncio
async def test_star_allows_a_global_write(projects, monkeypatch):
    monkeypatch.setenv(ALLOW, "*")
    stored = await remember_handler(
        {"content": MARKER, "is_global": True, "force": True}
    )
    assert stored["is_global"] is True
    assert MARKER in _alpha_context()


@pytest.mark.asyncio
async def test_anchor_cannot_rewrite_another_projects_memory(projects, monkeypatch):
    mid = await _alpha_memory(monkeypatch)
    with pytest.raises(ValidationError, match=r"^anchor: domain 'alpha' belongs"):
        await anchor.handler({"memory_id": mid, "reason": MARKER})
    assert not any(MARKER in c for c in _alpha_context())


@pytest.mark.asyncio
async def test_anchor_cannot_make_a_memory_global(projects):
    own = await remember_handler({"content": "beta note", "force": True})
    with pytest.raises(ValidationError, match=r"^anchor: is_global=true writes"):
        await anchor.handler({"memory_id": own["memory_id"], "is_global": True})


@pytest.mark.asyncio
async def test_anchor_cannot_change_a_global_memory(projects, monkeypatch):
    monkeypatch.setenv(ALLOW, "*")
    shared = await remember_handler(
        {"content": "shared", "is_global": True, "force": True}
    )
    monkeypatch.delenv(ALLOW)
    with pytest.raises(ValidationError, match=r"^anchor: memory \d+ is global"):
        await anchor.handler({"memory_id": shared["memory_id"], "reason": MARKER})


@pytest.mark.asyncio
async def test_supersede_cannot_target_another_projects_memory(projects, monkeypatch):
    mid = await _alpha_memory(monkeypatch)
    with pytest.raises(ValidationError, match=r"^remember: domain 'alpha' belongs"):
        await remember_handler({"content": MARKER, "supersedes_id": mid, "force": True})
    assert MARKER not in _alpha_context()


@pytest.mark.asyncio
async def test_curation_never_merges_into_another_projects_memory(
    projects, monkeypatch
):
    text = "the deploy script runs the migrations before the web workers"
    await _alpha_memory(monkeypatch, text)
    merged = await remember_handler({"content": text + " " + MARKER})
    assert merged["action"] != "merge"
    assert not any(MARKER in c for c in _alpha_context())


class _ReplicaStore:
    def __init__(self, *rows):
        self.rows, self.updates, self.selects = list(rows), [], []

    def _execute(self, sql, params=()):
        rows = self.rows if sql.lstrip().startswith("SELECT") else []
        if sql.lstrip().startswith("SELECT"):
            self.selects.append(sql)
        if not sql.lstrip().startswith("SELECT"):
            self.updates.append(params)
        return type("Cursor", (), {"fetchall": lambda _self: rows})()


@pytest.mark.parametrize(
    "row",
    [
        {"id": 7, "domain": "alpha", "is_global": False},
        {"id": 7, "domain": "", "is_global": True},
        {"id": 7, "domain": "", "is_global": False, "directory_context": "ALPHA"},
    ],
    ids=["other-project", "global", "other-projects-directory"],
)
def test_a_replica_of_a_row_this_session_may_not_change_is_not_refreshed(projects, row):
    if row.get("directory_context") == "ALPHA":  # Codex on PR #970
        row = row | {"directory_context": str(projects / "alpha")}
    store = _ReplicaStore(row)
    tags = ["memory-replica", "vpath:/x.md"]
    assert try_block_replica_upsert(MARKER, None, tags, "user", store) == (False, None)
    assert store.updates == []


def test_another_projects_replica_does_not_hide_this_sessions_own(projects):
    # Codex on PR #969: with LIMIT 1 the other project's row was the only one read,
    # so every sync from beta inserted one more row instead of refreshing its own.
    store = _ReplicaStore(
        {"id": 7, "domain": "alpha", "is_global": False},
        {"id": 9, "domain": "beta", "is_global": False},
    )
    tags = ["memory-replica", "vpath:/x.md"]
    assert try_block_replica_upsert(MARKER, None, tags, "user", store) == (True, 9)
    assert len(store.updates) == 1 and 9 in store.updates[0]
    # Every replica of the block is read, in a stable order: no LIMIT hides one.
    assert store.selects[0].endswith("'[\"memory-replica\"]'::jsonb ORDER BY id")
    assert store.selects[0].startswith(
        "SELECT id, domain, is_global, directory_context FROM memories "
    )


def test_seed_project_checks_the_domain_remember_will_use(projects):
    # directory inside alpha wins over domain=beta in remember: refused up front.
    with pytest.raises(ValidationError, match=r"^seed_project: domain 'alpha'"):
        seed_project._parse_args(
            {"directory": str(projects / "alpha"), "domain": "beta"}
        )


def test_seed_project_reports_the_domain_remember_resolves(projects, tmp_path):
    # Outside any known repository the explicit domain is resolved exactly as
    # remember resolves it (stripped, lowercased), never kept as the raw argument.
    _root, domain, _max, _dry = seed_project._parse_args(
        {"directory": str(tmp_path / "unregistered"), "domain": "  Shared-Notes "}
    )
    assert domain == "shared-notes"
