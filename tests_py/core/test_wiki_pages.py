"""Tests for core.wiki_pages — templates, frontmatter round-trip."""

from __future__ import annotations

import pytest

from mcp_server.core.wiki_pages import (
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


def test_empty_page_document() -> None:
    assert render_page(PageDocument()) == ""
