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


def test_slugify_strips_trailing_md_extension() -> None:
    """Regression — bug found 2026-05-12.

    Inputs that already look like .md filenames produced .md.md pages
    because every wiki callsite appends ``.md`` to the slug. 58 pages
    in the wiki had this shape (e.g. ``2234-decision-001-zero-
    dependencies.md.md``). Slug must never end in ``.md``.
    """
    assert slugify("001-zero-dependencies.md") == "001-zero-dependencies"
    assert slugify("foo.md") == "foo"
    # Iterated md chain — should collapse to base.
    assert slugify("foo.md.md") == "foo"
    assert slugify("foo.md.md.md") == "foo"


def test_slugify_preserves_non_md_extensions() -> None:
    """``file_path_slug`` callers depend on .py/.ts/etc. surviving."""
    assert slugify("login.py") == "login.py"
    assert slugify("config.yaml") == "config.yaml"


def test_adr_filename_no_double_md() -> None:
    """End-to-end: title that contains '.md' must not yield .md.md."""
    slug = slugify("001-zero-dependencies.md")
    assert adr_filename(2234, slug) == "2234-001-zero-dependencies.md"
    assert not adr_filename(2234, slug).endswith(".md.md")


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


def test_page_kinds_modern_plus_legacy() -> None:
    """ADR-2244: PAGE_KINDS contains all 8 modern + 6 legacy kinds.

    Modern kinds drive new writes; legacy kinds remain accepted by
    ``page_path`` / ``domain_page_path`` so existing pages under
    notes/specs/conventions/lessons/guides/files stay readable.
    """
    from mcp_server.core.wiki_layout import LEGACY_PAGE_KINDS, MODERN_PAGE_KINDS

    assert MODERN_PAGE_KINDS == (
        "tutorial",
        "how-to",
        "reference",
        "explanation",
        "adr",
        "runbook",
        "rfc",
        "journal",
    )
    assert LEGACY_PAGE_KINDS == (
        "specs",
        "guides",
        "conventions",
        "lessons",
        "notes",
        "files",
    )
    # The combined tuple must contain every modern + every legacy kind.
    assert set(PAGE_KINDS) == set(MODERN_PAGE_KINDS) | set(LEGACY_PAGE_KINDS)
    # No duplicates (e.g. journal is modern; must not appear twice).
    assert len(PAGE_KINDS) == len(set(PAGE_KINDS))
