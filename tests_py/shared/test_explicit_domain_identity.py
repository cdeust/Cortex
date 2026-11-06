"""An explicit domain keeps its identity; it is never remapped by substring (#721).

In the SciFact ingestion campaign, ``remember(domain="scifact-comparison")``
persisted every fact under ``harness-comparison``: ``resolve_domain`` treats
its input as a hint and returns the canonical of the longest known repository
fragment found inside it, and ``comparison`` is a fragment of the
``harness-comparison`` repository. These tests rebuild that registry from real
directories under ``tmp_path`` and check the explicit path through the
public ``remember`` handler as well as the resolver.

source: issue #721; ADR-0647"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mcp_server.shared import domain_mapping as dm


def _make_repo(dev_root: Path, name: str) -> None:
    git_dir = dev_root / name / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = https://github.com/org/{name}.git\n'
    )


@pytest.fixture
def registry_of(tmp_path, monkeypatch):
    """Point the domain registry at a dev root holding exactly ``names``."""

    def build(*names: str) -> None:
        dev_root = tmp_path / ("dev-" + "-".join(names))
        dev_root.mkdir()
        for name in names:
            _make_repo(dev_root, name)
        monkeypatch.setattr(dm, "_candidate_dev_roots", lambda: [dev_root])
        dm._build_registry.cache_clear()

    yield build
    dm._build_registry.cache_clear()


def test_hint_resolution_reproduces_the_substring_collision(registry_of):
    registry_of("harness-comparison")
    assert dm.resolve_domain("scifact-comparison") == "harness-comparison"


def test_explicit_domain_is_not_remapped_by_a_shared_fragment(registry_of):
    registry_of("harness-comparison")
    assert dm.resolve_explicit_domain("scifact-comparison") == "scifact-comparison"


def test_unrelated_repository_cannot_change_an_explicit_domain(registry_of):
    registry_of("cortex")
    before = dm.resolve_explicit_domain("SciFact-Comparison ")
    registry_of("cortex", "harness-comparison")
    assert dm.resolve_explicit_domain("SciFact-Comparison ") == before
    assert before == "scifact-comparison"


def test_exact_repository_name_still_maps_to_its_family(registry_of):
    registry_of("cortex", "cortex-cowork")
    assert dm.resolve_explicit_domain("cortex-cowork") == "cortex"
    assert dm.resolve_explicit_domain("Cortex") == "cortex"


def test_empty_explicit_domain_stays_empty(registry_of):
    registry_of("cortex")
    assert dm.resolve_explicit_domain("  ") == ""


def test_remember_persists_the_explicit_domain(registry_of):
    from mcp_server.handlers.forget import _get_store
    from mcp_server.handlers.remember import handler

    registry_of("harness-comparison")
    result = asyncio.run(
        handler(
            {
                "content": "SciFact claim 4983: the explicit corpus domain "
                "survives a repository fragment collision (#721)",
                "domain": "scifact-comparison",
                "force": True,
            }
        )
    )
    assert result["stored"] is True, result
    with _get_store()._conn.cursor() as cur:
        cur.execute("SELECT domain FROM memories WHERE id = %s", (result["memory_id"],))
        row = cur.fetchone()
    assert row is not None
    assert row["domain"] == "scifact-comparison"
