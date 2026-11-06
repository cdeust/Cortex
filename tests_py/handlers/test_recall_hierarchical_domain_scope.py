"""recall_hierarchical reads the domain identity remember writes (#721, slice 3).

``remember`` and ``recall`` resolve an explicit ``domain`` with
``resolve_explicit_domain`` (a family member maps to its canonical, any other
name is kept, lowercased). ``recall_hierarchical`` handed the raw argument to
``get_memories_for_domain``, so ``cortex-cowork`` or ``SciFact`` read a scope no
write ever used. Each test rebuilds the repository registry from real
directories under ``tmp_path`` and reads the domain the public handler hands to
the store.

source: issue #721; ADR-0647"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mcp_server.errors import ValidationError
from mcp_server.handlers import recall_hierarchical, remember
from mcp_server.shared import domain_mapping as dm


class _FakeStore:
    """Records the domain it is asked for and holds no memory."""

    def __init__(self) -> None:
        self.domains: list[str] = []

    def get_memories_for_domain(self, domain, **_kwargs):
        self.domains.append(domain)
        return []


def _make_repo(dev_root: Path, name: str) -> None:
    git_dir = dev_root / name / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = https://github.com/org/{name}.git\n'
    )


@pytest.fixture
def scoped_domain(tmp_path, monkeypatch):
    """Return the domain the public handler reads for ``domain``."""
    dev_root = tmp_path / "dev"
    for name in ("cortex", "cortex-cowork", "harness-comparison"):
        _make_repo(dev_root, name)
    monkeypatch.setattr(dm, "_candidate_dev_roots", lambda: [dev_root])
    dm._build_registry.cache_clear()
    store = _FakeStore()
    monkeypatch.setattr(recall_hierarchical, "_get_store", lambda: store)
    monkeypatch.setattr(recall_hierarchical, "get_embedding_engine", lambda: None)

    def run(domain):
        asyncio.run(recall_hierarchical.handler({"query": "q", "domain": domain}))
        return store.domains[-1]

    yield run
    dm._build_registry.cache_clear()


def test_family_member_is_read_under_its_canonical(scoped_domain):
    assert scoped_domain("cortex-cowork") == "cortex"


def test_explicit_name_is_read_as_written_lowercased(scoped_domain):
    assert scoped_domain(" SciFact-Comparison") == "scifact-comparison"


def test_substring_collision_is_not_remapped(scoped_domain):
    assert scoped_domain("scifact-comparison") != "harness-comparison"


@pytest.mark.parametrize("name", ["cortex-cowork", "SciFact-Comparison", "Cortex"])
def test_read_scope_equals_remember_write_scope(scoped_domain, name):
    assert scoped_domain(name) == remember._resolve_domain("", name)


def test_blank_domain_is_no_scope(scoped_domain):
    with pytest.raises(ValidationError):
        scoped_domain("   ")


def test_caller_arguments_are_not_changed(scoped_domain):
    args = {"query": "q", "domain": "Cortex-Cowork"}
    asyncio.run(recall_hierarchical._scoped_by_explicit_domain(args))
    assert args == {"query": "q", "domain": "Cortex-Cowork"}
