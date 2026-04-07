"""Tests for infrastructure.wiki_writer — atomic write, idempotency, prune."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from mcp_server.core.wiki_projection import WikiPage
from mcp_server.infrastructure.wiki_writer import sync


def _page(path: str, body: str) -> WikiPage:
    return WikiPage(path=PurePosixPath(path), markdown=body)


def test_sync_writes_pages(tmp_path: Path) -> None:
    pages = [_page("INDEX.md", "# Hello"), _page("a/INDEX.md", "# A")]
    result = sync(tmp_path, pages)
    assert result.written == 2
    assert result.skipped == 0
    assert result.pruned == 0
    assert (tmp_path / "INDEX.md").read_text() == "# Hello"
    assert (tmp_path / "a" / "INDEX.md").read_text() == "# A"


def test_sync_is_idempotent(tmp_path: Path) -> None:
    pages = [_page("INDEX.md", "# Hello")]
    sync(tmp_path, pages)
    result = sync(tmp_path, pages)
    assert result.written == 0
    assert result.skipped == 1


def test_sync_prunes_orphan_pages(tmp_path: Path) -> None:
    sync(tmp_path, [_page("INDEX.md", "# A"), _page("old/INDEX.md", "# old")])
    result = sync(tmp_path, [_page("INDEX.md", "# A")])
    assert result.pruned == 1
    assert not (tmp_path / "old" / "INDEX.md").exists()
    assert not (tmp_path / "old").exists()  # empty dir cleaned up


def test_sync_dry_run_makes_no_changes(tmp_path: Path) -> None:
    pages = [_page("INDEX.md", "# Hello")]
    result = sync(tmp_path, pages, dry_run=True)
    assert result.written == 1
    assert not (tmp_path / "INDEX.md").exists()
