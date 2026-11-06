"""recall scopes by the same domain identity remember writes (#721, slice 2).

``remember`` resolves an explicit ``domain`` with ``resolve_explicit_domain``
(a family member maps to its canonical, any other name is kept, lowercased).
``recall`` passed the raw argument to the store, so ``cortex-cowork`` or
``SciFact`` searched a scope no write ever used. Each test rebuilds the
repository registry from real directories under ``tmp_path`` and reads the
domain the public ``recall`` handler hands to the retrieval pipeline.

source: issue #721; ADR-0647"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mcp_server.handlers import recall, remember
from mcp_server.shared import domain_mapping as dm


class _StopError(Exception):
    """Raised by the fake pipeline once it has seen its arguments."""


def _make_repo(dev_root: Path, name: str) -> None:
    git_dir = dev_root / name / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = https://github.com/org/{name}.git\n'
    )


@pytest.fixture
def scoped_domain(tmp_path, monkeypatch):
    """Return the domain ``recall`` passes to ``pg_recall`` for ``domain``."""
    dev_root = tmp_path / "dev"
    for name in ("cortex", "cortex-cowork", "harness-comparison"):
        _make_repo(dev_root, name)
    monkeypatch.setattr(dm, "_candidate_dev_roots", lambda: [dev_root])
    dm._build_registry.cache_clear()
    monkeypatch.setattr(recall, "_get_store", lambda: object())
    monkeypatch.setattr(recall, "get_embedding_engine", lambda: object())
    seen: dict = {}

    def fake_pg_recall(**kwargs):
        seen.update(kwargs)
        raise _StopError

    monkeypatch.setattr(recall, "pg_recall", fake_pg_recall)

    def run(domain):
        with pytest.raises(_StopError):
            asyncio.run(recall._handler_impl({"query": "q", "domain": domain}))
        return seen["domain"]

    yield run
    dm._build_registry.cache_clear()


def test_family_member_is_searched_under_its_canonical(scoped_domain):
    assert scoped_domain("cortex-cowork") == "cortex"


def test_explicit_name_is_searched_as_written_lowercased(scoped_domain):
    assert scoped_domain(" SciFact-Comparison") == "scifact-comparison"


@pytest.mark.parametrize("name", ["cortex-cowork", "SciFact-Comparison", "Cortex"])
def test_recall_scope_equals_remember_write_scope(scoped_domain, name):
    assert scoped_domain(name) == remember._resolve_domain("", name)


@pytest.mark.parametrize("domain", [None, ""])
def test_no_domain_stays_unscoped(scoped_domain, domain):
    assert scoped_domain(domain) is None
