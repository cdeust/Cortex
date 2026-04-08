"""Tests for infrastructure.wiki_store — authoring primitives, no prune."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.infrastructure.wiki_store import (
    WikiExists,
    WikiMissing,
    append_section,
    list_pages,
    next_adr_number,
    read_page,
    write_page,
)


def test_create_writes_new_file(tmp_path: Path) -> None:
    result = write_page(tmp_path, "notes/hello.md", "# Hi\n")
    assert result.created is True
    assert (tmp_path / "notes" / "hello.md").read_text() == "# Hi\n"


def test_create_rejects_existing(tmp_path: Path) -> None:
    write_page(tmp_path, "notes/x.md", "body")
    with pytest.raises(WikiExists):
        write_page(tmp_path, "notes/x.md", "other")


def test_replace_overwrites(tmp_path: Path) -> None:
    write_page(tmp_path, "notes/y.md", "first")
    write_page(tmp_path, "notes/y.md", "second", mode="replace")
    assert (tmp_path / "notes" / "y.md").read_text() == "second"


def test_append_adds_content(tmp_path: Path) -> None:
    write_page(tmp_path, "notes/z.md", "first\n")
    write_page(tmp_path, "notes/z.md", "second", mode="append")
    text = (tmp_path / "notes" / "z.md").read_text()
    assert "first" in text and "second" in text
    assert text.index("first") < text.index("second")


def test_append_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(WikiMissing):
        write_page(tmp_path, "notes/nope.md", "x", mode="append")


def test_read_page_returns_none_for_missing(tmp_path: Path) -> None:
    assert read_page(tmp_path, "notes/missing.md") is None


def test_read_page_returns_content(tmp_path: Path) -> None:
    write_page(tmp_path, "notes/r.md", "hello world")
    assert read_page(tmp_path, "notes/r.md") == "hello world"


def test_append_section_creates_heading(tmp_path: Path) -> None:
    write_page(tmp_path, "notes/s.md", "# Title\n")
    append_section(tmp_path, "notes/s.md", "Extras", "more info")
    text = (tmp_path / "notes" / "s.md").read_text()
    assert "## Extras" in text
    assert "more info" in text


def test_append_section_missing_page(tmp_path: Path) -> None:
    with pytest.raises(WikiMissing):
        append_section(tmp_path, "notes/gone.md", "X", "y")


def test_list_pages_filters_by_kind(tmp_path: Path) -> None:
    write_page(tmp_path, "adr/0001-foo.md", "a")
    write_page(tmp_path, "specs/bar.md", "b")
    write_page(tmp_path, "notes/baz.md", "c")
    all_pages = list_pages(tmp_path)
    assert len(all_pages) == 3
    adrs = list_pages(tmp_path, kind="adr")
    assert adrs == ["adr/0001-foo.md"]


def test_list_pages_skips_generated(tmp_path: Path) -> None:
    write_page(tmp_path, "notes/x.md", "x")
    (tmp_path / ".generated").mkdir()
    (tmp_path / ".generated" / "INDEX.md").write_text("toc")
    pages = list_pages(tmp_path)
    assert "notes/x.md" in pages
    assert not any(".generated" in p for p in pages)


def test_next_adr_number_empty(tmp_path: Path) -> None:
    assert next_adr_number(tmp_path) == 1


def test_next_adr_number_increments(tmp_path: Path) -> None:
    write_page(tmp_path, "adr/0001-foo.md", "a")
    write_page(tmp_path, "adr/0005-bar.md", "b")
    assert next_adr_number(tmp_path) == 6


def test_path_escape_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_page(tmp_path, "../../etc/passwd", "nope")
