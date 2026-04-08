"""Tests for core.wiki_layout — path contract, slug, parsing."""

from __future__ import annotations

import pytest

from mcp_server.core.wiki_layout import (
    PAGE_KINDS,
    adr_filename,
    file_path_slug,
    index_path,
    page_path,
    parse_page_path,
    slugify,
)


def test_slugify_basic() -> None:
    assert slugify("Use pgvector for Retrieval!") == "use-pgvector-for-retrieval"


def test_slugify_length_capped() -> None:
    long = "a" * 200
    assert len(slugify(long)) <= 80


def test_slugify_empty() -> None:
    assert slugify("") == "unknown"
    assert slugify("   ") == "unknown"
    assert slugify("!!!") == "unknown"


def test_file_path_slug() -> None:
    assert (
        file_path_slug("mcp_server/handlers/wiki_write.py")
        == "mcp_server-handlers-wiki_write.py"
    )


def test_adr_filename_zero_padded() -> None:
    assert adr_filename(7, "foo-bar") == "0007-foo-bar.md"


def test_page_path_valid_kinds() -> None:
    assert str(page_path("adr", "0001-x.md")) == "adr/0001-x.md"
    assert str(page_path("specs", "y.md")) == "specs/y.md"


def test_page_path_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        page_path("bogus", "x.md")


def test_parse_page_path_roundtrip() -> None:
    assert parse_page_path("adr/0001-x.md") == ("adr", "0001-x.md")
    assert parse_page_path("specs/y.md") == ("specs", "y.md")


def test_parse_page_path_rejects_generated() -> None:
    assert parse_page_path(".generated/INDEX.md") is None


def test_index_path() -> None:
    assert str(index_path()) == ".generated/INDEX.md"


def test_page_kinds_stable() -> None:
    assert PAGE_KINDS == ("adr", "specs", "files", "notes")
