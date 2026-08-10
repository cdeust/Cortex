"""Tests for core.wiki_pages — templates, frontmatter round-trip."""

from __future__ import annotations

import pytest

from mcp_server.shared.wiki_pages import (
    PageDocument,
    build_adr,
    build_file_doc,
    build_note,
    build_spec,
    parse_page,
    render_page,
)


def test_build_adr_contains_sections() -> None:
    text = build_adr(
        number=1,
        title="Use pgvector",
        context="ctx",
        decision="dec",
        consequences="cons",
    )
    assert "---" in text
    assert "kind: adr" in text
    assert "number: 0001" in text
    assert "# ADR-0001: Use pgvector" in text
    assert "## Status" in text
    assert "## Context" in text
    assert "## Decision" in text
    assert "## Consequences" in text


def test_build_adr_rejects_unknown_status() -> None:
    with pytest.raises(ValueError):
        build_adr(
            number=1,
            title="t",
            context="c",
            decision="d",
            consequences="q",
            status="maybe",
        )


def test_build_spec_minimal() -> None:
    text = build_spec(title="Feature X", summary="sum")
    assert "kind: spec" in text
    assert "# Feature X" in text
    assert "## Summary" in text


def test_build_file_doc_minimal() -> None:
    text = build_file_doc(file_path="src/x.py", purpose="Does X")
    assert "kind: file" in text
    assert "file: src/x.py" in text
    assert "# `src/x.py`" in text


def test_build_note_minimal() -> None:
    text = build_note(title="Note", body="content body")
    assert "kind: note" in text
    assert "# Note" in text
    assert "content body" in text


def test_parse_page_frontmatter_and_body() -> None:
    text = "---\ntitle: hi\ntags: [a, b]\n---\n\nbody line\n"
    doc = parse_page(text)
    assert doc.frontmatter["title"] == "hi"
    assert doc.frontmatter["tags"] == ["a", "b"]
    assert "body line" in doc.body


def test_parse_page_no_frontmatter() -> None:
    doc = parse_page("# just a body\n")
    assert doc.frontmatter == {}
    assert doc.body == "# just a body\n"


def test_render_roundtrip() -> None:
    original = build_adr(
        number=3,
        title="Test",
        context="c",
        decision="d",
        consequences="x",
    )
    parsed = parse_page(original)
    re_rendered = render_page(parsed)
    # Frontmatter is emitted deterministically (sorted); body stable.
    assert parse_page(re_rendered).frontmatter == parsed.frontmatter
    assert "## Decision" in re_rendered


def test_parse_page_strips_quoted_scalar_value() -> None:
    """Reproduction (wiki.pages.title corruption, 36 rows, 2026-07-14):

    a scalar value quoted per YAML convention because it contains a
    colon (``title: "Public API surface: automatised-pipeline"``) must
    have its surrounding quotes stripped, matching the block-list item
    branch (line ~103) and the inline-list branch (``_strip_inline_list``)
    which already do this. Before the fix, the scalar branch assigned
    ``raw_stripped`` verbatim, leaving the literal quote characters in
    ``fm["title"]`` and, downstream, in ``wiki.pages.title``.
    """
    text = (
        "---\n"
        'title: "Public API surface: automatised-pipeline"\n'
        "kind: reference\n"
        "---\n\nbody\n"
    )
    doc = parse_page(text)
    assert doc.frontmatter["title"] == "Public API surface: automatised-pipeline"


def test_parse_page_strips_duplicated_key_label() -> None:
    """Reproduction (wiki.pages.title corruption, 26 rows, 2026-07-14):

    real files under ~/.claude/methodology/wiki/ (authored by an LLM
    completion routed verbatim through write_governed_page, see
    wiki_write.py) contain a duplicated ``title: title: "..."`` label —
    the frontmatter's own key echoed into its own value. ``line.partition(":")``
    only ever strips the FIRST ``title:`` label, so the second one used to
    ride along into ``fm["title"]`` verbatim and then into
    ``wiki.pages.title`` via ``wiki_migrate.page_row_from_md``. Confirmed
    against the actual on-disk file (id 913,
    ``reference/_general/4196397-title-public-api-surface-automatised-pipeline.md``).
    """
    text = (
        '---\ntitle: title: "Public API surface: automatised-pipeline"\n'
        "kind: reference\n---\n\nbody\n"
    )
    doc = parse_page(text)
    assert doc.frontmatter["title"] == "Public API surface: automatised-pipeline"

    # Unquoted duplicated-label variant (id 2916 on disk: title: title: agentic-ai —
    # tutorials)
    text2 = (
        "---\ntitle: title: agentic-ai — tutorials\nkind: explanation\n---\n\nbody\n"
    )
    doc2 = parse_page(text2)
    assert doc2.frontmatter["title"] == "agentic-ai — tutorials"


def test_parse_page_does_not_strip_legitimate_colon_value() -> None:
    """A value that legitimately starts with the key name followed by other
    text (not the ``key: `` duplicate-label pattern) must be preserved."""
    text = "---\ntitle: titleist golf clubs review\n---\n\nbody\n"
    doc = parse_page(text)
    assert doc.frontmatter["title"] == "titleist golf clubs review"


def test_empty_page_document() -> None:
    assert render_page(PageDocument()) == ""
