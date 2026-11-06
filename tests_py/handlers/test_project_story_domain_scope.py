"""get_project_story reads the domain identity remember writes (#721, slice 5).

``remember``, ``recall``, ``recall_hierarchical`` and ``narrative`` resolve an
explicit ``domain`` with ``resolve_explicit_domain`` (a family member maps to
its canonical, any other name is kept, lowercased). ``get_project_story``
handed the raw argument to ``get_memories_for_domain``, so ``cortex-cowork``
or ``SciFact`` told the story of a scope no write ever used. Each test rebuilds
the repository registry from real directories under ``tmp_path`` and reads the
domain the public handler hands to the store.

source: issue #721; ADR-0647"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mcp_server.handlers import get_project_story, remember
from mcp_server.shared import domain_mapping as dm


class _FakeStore:
    """Records which scope it is asked for and holds no memory."""

    def __init__(self) -> None:
        self.domains: list[str] = []
        self.hot_reads = 0

    def get_memories_for_domain(self, domain, **_kwargs):
        self.domains.append(domain)
        return []

    def get_hot_memories(self, **_kwargs):
        self.hot_reads += 1
        return []


def _make_repo(dev_root: Path, name: str) -> None:
    git_dir = dev_root / name / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = https://github.com/org/{name}.git\n'
    )


@pytest.fixture
def store(tmp_path, monkeypatch):
    dev_root = tmp_path / "dev"
    for name in ("cortex", "cortex-cowork", "harness-comparison"):
        _make_repo(dev_root, name)
    monkeypatch.setattr(dm, "_candidate_dev_roots", lambda: [dev_root])
    dm._build_registry.cache_clear()
    fake = _FakeStore()
    monkeypatch.setattr(get_project_story, "_get_store", lambda: fake)
    yield fake
    dm._build_registry.cache_clear()


def _scope(store: _FakeStore, domain: str) -> str:
    asyncio.run(get_project_story.handler({"domain": domain}))
    return store.domains[-1]


def test_family_member_is_read_under_its_canonical(store):
    assert _scope(store, "cortex-cowork") == "cortex"


def test_explicit_name_is_read_as_written_lowercased(store):
    assert _scope(store, " SciFact-Comparison") == "scifact-comparison"


def test_substring_collision_is_not_remapped(store):
    assert _scope(store, "scifact-comparison") != "harness-comparison"


@pytest.mark.parametrize("name", ["cortex-cowork", "SciFact-Comparison", "Cortex"])
def test_read_scope_equals_remember_write_scope(store, name):
    assert _scope(store, name) == remember._resolve_domain("", name)


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_domain_is_no_scope(store, blank):
    asyncio.run(get_project_story.handler({"domain": blank}))
    assert store.domains == []
    assert store.hot_reads == 1
