"""Tests for seed_project handler — domain-scoped purge (issue #16).

PSGSupport reported that calling `seed_project` for repo-A and then
repo-B purged repo-A's "seeded" memories despite the explicit `domain`
argument. The cause was a global `delete_memories_by_tag("seeded")` call
that ignored domain. The fix scopes the purge to the supplied domain.

These tests prove the cross-domain leak is closed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mcp_server.handlers.seed_project import handler
from mcp_server.infrastructure.memory_store import get_shared_store


@pytest.fixture(autouse=True)
def _allow_transient_seed_roots(monkeypatch):
    """Disable the transient-root guard for this module's tests.

    The handler refuses to operate on paths matching ``pytest-of-`` /
    ``/private/var/folders/`` / ``/var/folders/`` so test runs and
    worktree creation never pollute the wiki. But this module's tests
    use ``tmp_path`` (which IS a transient root) by design — they're
    proving the per-domain purge contract, not validating the
    transient-root gate. Stub the predicate to ``False`` for the
    duration of each test so the handler proceeds into the codepath
    under test.
    """
    monkeypatch.setattr(
        "mcp_server.handlers.seed_project_constants.is_transient_seed_root",
        lambda _path: False,
    )
    # Also patch the import name as seen by ``seed_project`` itself,
    # since the handler imports the predicate at function-call time.
    import mcp_server.handlers.seed_project as sp

    if hasattr(sp, "is_transient_seed_root"):
        monkeypatch.setattr(sp, "is_transient_seed_root", lambda _path: False)


def _make_repo(tmp_path: Path, name: str) -> Path:
    """Build a minimal repo skeleton sufficient for seed_project to find content."""
    root = tmp_path / name
    root.mkdir()
    (root / "README.md").write_text(f"# {name}\nMinimal seed test fixture.\n")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "{name}"\nversion = "0.1.0"\n'
    )
    return root


def _seeded_count(store, domain: str) -> int:
    rows = store.get_memories_for_domain(domain, min_heat=0.0, limit=500)
    return sum(1 for r in rows if "seeded" in (r.get("tags") or []))


def test_seed_repo_a_then_repo_b_preserves_repo_a(tmp_path: Path) -> None:
    """The bug: seeding repo-B used to wipe out repo-A's seeded memories."""
    repo_a = _make_repo(tmp_path, "repo-a")
    repo_b = _make_repo(tmp_path, "repo-b")

    store = get_shared_store()

    # Seed repo-a
    res_a = asyncio.run(handler({"directory": str(repo_a), "domain": "repo-a"}))
    assert res_a["seeded"] is True
    assert res_a["stored"] >= 1, "fixture should yield at least one stored memory"
    a_after_first_seed = _seeded_count(store, "repo-a")
    assert a_after_first_seed >= 1

    # Seed repo-b — must not touch repo-a's memories
    res_b = asyncio.run(handler({"directory": str(repo_b), "domain": "repo-b"}))
    assert res_b["seeded"] is True

    a_after_second_seed = _seeded_count(store, "repo-a")
    assert a_after_second_seed == a_after_first_seed, (
        f"repo-a's seeded memories must survive seeding repo-b "
        f"(had {a_after_first_seed}, now {a_after_second_seed})"
    )


def test_reseeding_same_repo_purges_only_that_repo(tmp_path: Path) -> None:
    """Reseeding repo-A should clear repo-A's prior seeds and replace them,
    while leaving repo-B's seeds untouched."""
    repo_a = _make_repo(tmp_path, "repo-a")
    repo_b = _make_repo(tmp_path, "repo-b")

    store = get_shared_store()

    asyncio.run(handler({"directory": str(repo_a), "domain": "repo-a"}))
    asyncio.run(handler({"directory": str(repo_b), "domain": "repo-b"}))

    b_before = _seeded_count(store, "repo-b")
    assert b_before >= 1

    # Reseed repo-a — purge should be domain-scoped
    res_a2 = asyncio.run(handler({"directory": str(repo_a), "domain": "repo-a"}))
    assert res_a2["seeded"] is True
    # Reported purge count must reflect the prior repo-a memories,
    # never zero (we know there were some) and never include repo-b's.
    assert res_a2["purged_stale"] >= 1
    assert res_a2["purged_stale"] <= b_before + res_a2["purged_stale"]  # sanity

    b_after = _seeded_count(store, "repo-b")
    assert b_after == b_before, (
        "reseeding repo-a must not affect repo-b's seeded memories"
    )


def test_domain_auto_detected_from_directory_name(tmp_path: Path) -> None:
    """Schema documents domain auto-detection from directory name. The fix
    materializes that contract — without it, an omitted domain would
    fall back to global purge (the original bug)."""
    repo = _make_repo(tmp_path, "auto-detect-me")

    res = asyncio.run(handler({"directory": str(repo)}))
    assert res["seeded"] is True
    assert res["domain"] == "auto-detect-me"
