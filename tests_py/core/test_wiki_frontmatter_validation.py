"""Tests for core.wiki_frontmatter_validation — issue #107.

write_governed_page persisted caller-supplied markdown verbatim without
re-deriving/validating frontmatter, which is how the `title: title: "..."`
corruption (fixed reactively at read-time by commit 53712df8/PR #104) got
onto disk in the first place. These tests cover the write-time gate that
closes the corruption CLASS: normalize (round-trip through parse_page +
render_page) for anything parse_page can repair, reject only the one
shape it cannot (an unclosed frontmatter fence).
"""

from __future__ import annotations

import pytest

from mcp_server.core.wiki_frontmatter_validation import (
    UnclosedFrontmatterError,
    normalize_frontmatter,
)
from mcp_server.core.wiki_pages import parse_page


def test_duplicated_key_label_is_normalized_to_canonical_form() -> None:
    """Reproduction of the exact corruption signature from commit 53712df8:
    an LLM-authored page's own frontmatter echoed the key into its value.
    """
    corrupt = (
        "---\n"
        'title: title: "Public API surface: automatised-pipeline"\n'
        "kind: reference\n"
        "---\n\nBody text.\n"
    )
    normalized = normalize_frontmatter(corrupt)

    doc = parse_page(normalized)
    assert doc.frontmatter["title"] == "Public API surface: automatised-pipeline"
    assert "title: title:" not in normalized
    # Persisted form no longer carries the raw duplicated label at all.
    assert normalized.count("title:") == 1


def test_healthy_page_round_trips_unchanged() -> None:
    """Idempotence: a page already in canonical form (as any build_*
    template already emits) must be persisted byte-identical.
    """
    from mcp_server.core.wiki_pages import build_note

    healthy = build_note(title="A clean note", body="Nothing to fix here.")

    normalized = normalize_frontmatter(healthy)

    assert normalized == healthy


def test_unclosed_frontmatter_fence_is_rejected() -> None:
    """The one shape parse_page cannot repair: no closing '---' means every
    remaining line -- including the intended body -- is swallowed as a
    frontmatter key/value pair, destroying the body. Must be rejected,
    not silently persisted.
    """
    unclosed = "---\ntitle: Something\nkind: note\n\nThis was meant to be the body.\n"

    with pytest.raises(UnclosedFrontmatterError):
        normalize_frontmatter(unclosed)


def test_plain_markdown_with_no_frontmatter_is_untouched() -> None:
    plain = "# Just a heading\n\nSome prose, no frontmatter at all.\n"

    assert normalize_frontmatter(plain) == plain


def test_quoted_scalar_value_is_normalized() -> None:
    quoted = (
        "---\n"
        'title: "Public API surface: automatised-pipeline"\n'
        "kind: reference\n"
        "---\n\nBody.\n"
    )
    normalized = normalize_frontmatter(quoted)
    doc = parse_page(normalized)
    assert doc.frontmatter["title"] == "Public API surface: automatised-pipeline"
