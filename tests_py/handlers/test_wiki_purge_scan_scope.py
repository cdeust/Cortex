"""Issue #622, secondary defect — what ``wiki_purge`` can actually reach.

``_PAGE_DIRS`` was a hand-kept copy of the page-kind list. It had drifted
from the path contract in ``shared.wiki_layout``, so every page under a
kind it had never heard of was skipped in silence: the stray page the
memory-to-page loop wrote under ``rfc/`` survived a purge that removed
its twin under ``reference/``, and had to be deleted by hand. The result
reported ``scanned`` with no total, so the caller could not tell that
most of the wiki was never looked at.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.handlers import wiki_purge
from mcp_server.shared.wiki_layout import PAGE_KINDS


@pytest.fixture()
def wiki_root(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "wiki"
    root.mkdir()
    monkeypatch.setattr(wiki_purge, "WIKI_ROOT", str(root))
    return root


def _write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\ntitle: {path.stem}\nkind: note\n---\n\n# {path.stem}\n\n{body}\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_purge_reaches_a_page_under_a_modern_kind_directory(wiki_root):
    """``rfc/`` is a kind the pipeline emits; the purge never saw it."""
    _write(wiki_root, "rfc/_general/82-title-architecture-overview.md", "thin.")
    _write(wiki_root, "notes/_general/1-also-thin.md", "thin.")

    out = await wiki_purge.handler({"apply": True})

    assert out["purged_paths"]
    purged = {Path(p).as_posix() for p in out["purged_paths"]}
    assert "rfc/_general/82-title-architecture-overview.md" in purged


@pytest.mark.asyncio
async def test_purge_reports_the_total_it_scanned_against(wiki_root):
    """``scanned`` alone hid that most of the wiki was skipped."""
    _write(wiki_root, "rfc/_general/a.md", "thin.")
    _write(wiki_root, "notes/_general/b.md", "thin.")
    _write(wiki_root, "_kinds/adr.md", "schema file, never a page.")
    _write(wiki_root, "handbook/_general/c.md", "not a known kind at all.")

    out = await wiki_purge.handler({"apply": False, "kind": "notes"})

    assert out["wiki_pages_total"] == 2
    assert out["scanned"] == 1
    assert out["unscanned"] == 1
    assert out["unrecognised_dirs"] == ["handbook"]


@pytest.mark.asyncio
async def test_purge_full_sweep_leaves_nothing_unscanned(wiki_root):
    _write(wiki_root, "rfc/_general/a.md", "thin.")
    _write(wiki_root, "explanation/_general/b.md", "thin.")
    _write(wiki_root, "_rules/default.md", "schema file, never a page.")

    out = await wiki_purge.handler({"apply": False})

    assert out["wiki_pages_total"] == out["scanned"] == 2
    assert out["unscanned"] == 0
    assert out["unrecognised_dirs"] == []


def test_every_directory_the_pipeline_emits_is_one_purge_scans():
    """No second hand-kept copy of the kind list (the ADR-1077 pattern)."""
    from mcp_server.core.draft_compiler import (
        DRAFT_KIND_DIR_FALLBACK,
        DRAFT_KIND_DIRS,
    )
    from mcp_server.core.wiki_sync import _MODERN_KIND_TO_DIR

    emitted = (
        set(_MODERN_KIND_TO_DIR.values())
        | set(DRAFT_KIND_DIRS.values())
        | {DRAFT_KIND_DIR_FALLBACK}
    )

    assert emitted <= set(PAGE_KINDS)
    assert emitted <= wiki_purge._PAGE_DIRS


def test_the_purge_kind_filter_offers_every_page_kind():
    """The tool's enum is the same list, not a third copy of it."""
    kind_enum = wiki_purge.schema["inputSchema"]["properties"]["kind"]["enum"]

    assert set(kind_enum) == set(PAGE_KINDS)
