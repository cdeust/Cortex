"""A write stores the domain its scope check resolved (GHSA-7848-qh48-mx2w).

Review 1 of PR #969, B1: `ingest_prd` and `ingest_document` checked the resolved
domain and stored the raw argument. `_group_repos` can register a directory name as
an alias of a project whose canonical differs while that same name is another
family's canonical: rows stored under the raw name reach that family's hot memories.
"""

from __future__ import annotations

import pytest

from mcp_server.errors import ValidationError
from mcp_server.handlers import _write_scope
from mcp_server.shared import domain_mapping
from tests_py.handlers.test_ghsa_7848_cross_project_write import (
    projects as _projects,
)

projects = _projects  # the fixture, registered in this module under its name


@pytest.fixture
def aliased(projects, monkeypatch):
    """`family` is a name that resolves to the session's project `beta`."""
    real = domain_mapping.resolve_explicit_domain
    alias = lambda name: "beta" if name.strip().lower() == "family" else real(name)  # noqa: E731
    monkeypatch.setattr(_write_scope, "resolve_explicit_domain", alias)
    return projects


def test_the_check_returns_the_domain_it_resolved(aliased):
    assert _write_scope.require_writable_domain("family", "t") == "beta"
    assert _write_scope.require_writable_domain(" Beta ", "t") == "beta"
    # A shared domain names no project: it is stored as given.
    assert _write_scope.require_writable_domain("Team-Notes", "t") == "Team-Notes"
    assert _write_scope.require_writable_domain("", "t") == ""
    assert _write_scope.require_writable_domain(None, "t") == ""


@pytest.mark.asyncio
async def test_ingest_prd_stores_the_resolved_domain_never_the_alias(
    aliased, monkeypatch
):
    from mcp_server.handlers import ingest_prd

    rows = []

    class Store:
        def insert_memory(self, record):
            rows.append(record)
            return len(rows)

    monkeypatch.setattr(ingest_prd, "write_page", lambda *a, **k: None)
    monkeypatch.setattr(ingest_prd, "_get_store", lambda: Store())
    text = "# Plan\n\n## Decisions\n\n- keep it\n\n## Requirements\n\n- ship it\n"
    await ingest_prd.handler({"content": text, "domain": "family"})
    assert rows and {row["domain"] for row in rows} == {"beta"}


@pytest.mark.asyncio
async def test_ingest_document_stores_the_resolved_domain_never_the_alias(
    aliased, tmp_path, monkeypatch
):
    from mcp_server.handlers import ingest_document

    seen = []

    async def persist(path, parsed, prov, domain):
        seen.append(domain)
        return {"ingested": True}

    monkeypatch.setattr(ingest_document, "_persist", persist)
    page = tmp_path / "export.html"
    page.write_text("<h1>Onboarding</h1><p>welcome</p>", encoding="utf-8")
    await ingest_document.handler({"path": str(page), "domain": "family"})
    assert seen == ["beta"]


# Codex on PR #969: a directory name can be an alias of one project (`family` is the
# directory of the repository whose domain is `beta`) and the canonical domain of
# another repository family (`family-one`, `family-two`). A domain that is an
# identity already (from a path, from a stored row) is never resolved a second time.
@pytest.fixture
def collision(aliased, monkeypatch):
    """`family` is both an alias of `beta` and another family's canonical domain."""
    monkeypatch.setattr(
        _write_scope, "project_domains", lambda: frozenset({"alpha", "beta", "family"})
    )
    return aliased


def test_a_family_writes_in_its_own_domain_despite_the_alias(collision, monkeypatch):
    monkeypatch.setattr(_write_scope, "session_domain", lambda environ=None: "family")
    _write_scope.require_writable_canonical("family", "remember")
    assert _write_scope.memory_writable({"domain": "family"}) is True


def test_the_aliased_project_cannot_change_the_familys_rows(collision):
    row = {"id": 3, "domain": "family", "is_global": False}
    assert _write_scope.memory_writable(row) is False
    with pytest.raises(ValidationError, match=r"^anchor: domain 'family' belongs"):
        _write_scope.require_writable_memory(row, "anchor")
    with pytest.raises(ValidationError, match=r"^remember: domain 'family' belongs"):
        _write_scope.require_writable_canonical(" Family ", "remember")


def test_the_alias_given_as_a_name_still_resolves_to_the_sessions_project(collision):
    assert _write_scope.require_writable_domain("family", "ingest_prd") == "beta"


def test_a_resolved_domain_of_no_known_project_stays_writable(collision):
    _write_scope.require_writable_canonical("team-notes", "remember")
    _write_scope.require_writable_canonical("", "remember")
    _write_scope.require_writable_canonical(None, "remember")
    _write_scope.require_writable_canonical("beta", "remember")
