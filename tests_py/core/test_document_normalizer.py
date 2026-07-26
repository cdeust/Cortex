"""Unit tests for the pure document normalizer (issue #192).

Assertions are exact (full frontmatter, exact table/summary strings) so the
mutation suite kills string/structure mutants — a normalizer whose output a
consumer parses cannot afford a silently drifted literal (§12).
"""

from __future__ import annotations

from mcp_server.core.document_model import (
    DocumentProvenance,
    DocumentSection,
    DocumentTable,
    ParsedDocument,
)
from mcp_server.core.document_normalizer import (
    NormalizedDocument,
    normalize_document,
    slugify,
)

_PROV = DocumentProvenance(
    source="/docs/x.docx", version="deadbeef", source_kind="docx"
)


def _doc(sections, image_count=0, title="Doc"):
    return ParsedDocument(title=title, sections=sections, image_count=image_count)


def _lines(md: str) -> list[str]:
    return md.splitlines()


class TestFrontmatter:
    def test_frontmatter_is_exact(self):
        n = normalize_document(
            _doc([DocumentSection("H", 1, "body")], title="My Doc"), _PROV
        )
        head = _lines(n.wiki_markdown)[:13]
        assert head == [
            "---",
            "title: My Doc",
            "kind: reference",
            "tags: [document, ingest, docx]",
            "source: /docs/x.docx",
            "source_kind: docx",
            "version: deadbeef",
            "---",
            "",
            "# My Doc",
            "",
            "> Ingested from `/docs/x.docx` (version `deadbeef`).",
            "",
        ]

    def test_tags_use_source_kind(self):
        prov = DocumentProvenance("/p.xml", "v1", "confluence-export")
        n = normalize_document(_doc([DocumentSection("H", 1, "b")]), prov)
        assert "tags: [document, ingest, confluence-export]" in n.wiki_markdown
        assert "source_kind: confluence-export" in n.wiki_markdown


class TestWikiPath:
    def test_wiki_path_is_documents_slug(self):
        n = normalize_document(_doc([], title="My Cool Doc"), _PROV)
        assert n.wiki_rel_path == "documents/my-cool-doc.md"


class TestFullRender:
    def test_full_wiki_markdown_is_exact(self):
        # Pins the whole document assembly — frontmatter, spacing, section
        # block, and the trailing-newline trim (rstrip, not lstrip).
        n = normalize_document(
            _doc([DocumentSection("Intro", 1, "hello")], title="T"), _PROV
        )
        assert n.wiki_markdown == (
            "---\n"
            "title: T\n"
            "kind: reference\n"
            "tags: [document, ingest, docx]\n"
            "source: /docs/x.docx\n"
            "source_kind: docx\n"
            "version: deadbeef\n"
            "---\n"
            "\n"
            "# T\n"
            "\n"
            "> Ingested from `/docs/x.docx` (version `deadbeef`).\n"
            "\n"
            "## Intro\n"
            "\n"
            "hello\n"
        )

    def test_no_trailing_blank_lines(self):
        n = normalize_document(_doc([DocumentSection("H", 1, "body")]), _PROV)
        assert n.wiki_markdown.endswith("body\n")
        assert not n.wiki_markdown.endswith("body\n\n")


class TestSummary:
    def test_summary_is_exact_with_counts_and_sections(self):
        sections = [DocumentSection("Intro", 1, "a"), DocumentSection("Body", 1, "b")]
        n = normalize_document(_doc(sections, image_count=2, title="T"), _PROV)
        assert n.summary == (
            "Document ingested: 'T' from /docs/x.docx "
            "(2 sections, 2 images skipped). Sections: Intro, Body."
        )

    def test_summary_omits_sections_clause_when_no_headings(self):
        n = normalize_document(_doc([DocumentSection("", 0, "body")], title="T"), _PROV)
        assert "Sections:" not in n.summary
        assert "(1 sections, 0 images skipped)." in n.summary

    def test_summary_caps_section_list_at_eight(self):
        sections = [DocumentSection(f"H{i}", 1, "b") for i in range(10)]
        n = normalize_document(_doc(sections, title="T"), _PROV)
        assert "H7" in n.summary and "H8" not in n.summary


class TestSections:
    def test_non_empty_section_becomes_memory_exact(self):
        n = normalize_document(_doc([DocumentSection("Intro", 1, "hello")]), _PROV)
        assert len(n.section_memories) == 1
        assert n.section_memories[0].heading == "Intro"
        assert n.section_memories[0].content == "[Intro]\n\nhello"

    def test_preamble_section_memory_labelled_document_body(self):
        n = normalize_document(_doc([DocumentSection("", 0, "loose text")]), _PROV)
        assert n.section_memories[0].heading == "(document body)"
        assert n.section_memories[0].content == "[(document body)]\n\nloose text"

    def test_empty_section_produces_no_memory_but_renders_heading(self):
        n = normalize_document(_doc([DocumentSection("Bare", 1, "")]), _PROV)
        assert n.section_memories == []
        assert "## Bare" in n.wiki_markdown.splitlines()

    def test_heading_hash_depth_tracks_level_exact_line(self):
        n = normalize_document(
            _doc([DocumentSection("A", 1, "x"), DocumentSection("B", 2, "y")]), _PROV
        )
        lines = n.wiki_markdown.splitlines()
        # Exact-line membership: level 1 → '## ', level 2 → '### ' (a substring
        # check would let '### A' satisfy '## A').
        assert "## A" in lines and "### A" not in lines
        assert "### B" in lines and "#### B" not in lines

    def test_heading_and_body_joined_by_blank_line(self):
        n = normalize_document(_doc([DocumentSection("H", 1, "body")]), _PROV)
        assert "## H\n\nbody" in n.wiki_markdown

    def test_heading_hash_capped_at_six_exact_line(self):
        n = normalize_document(_doc([DocumentSection("Deep", 6, "x")]), _PROV)
        lines = n.wiki_markdown.splitlines()
        assert "###### Deep" in lines
        assert "####### Deep" not in lines


class TestTableRendering:
    def test_square_table_exact(self):
        section = DocumentSection(
            "Data", 1, "", tables=[DocumentTable(rows=[["A", "B"], ["1", "2"]])]
        )
        n = normalize_document(_doc([section]), _PROV)
        assert "| A | B |\n| --- | --- |\n| 1 | 2 |" in n.wiki_markdown

    def test_ragged_header_padded_to_widest(self):
        section = DocumentSection(
            "D", 1, "", tables=[DocumentTable(rows=[["A"], ["1", "2", "3"]])]
        )
        n = normalize_document(_doc([section]), _PROV)
        # Header padded to width 3; separator has 3 columns.
        assert "| A |  |  |" in n.wiki_markdown
        assert "| --- | --- | --- |" in n.wiki_markdown
        assert "| 1 | 2 | 3 |" in n.wiki_markdown

    def test_short_body_row_padded_with_empty_cells_exact(self):
        # A body row narrower than the header must be padded with EMPTY cells
        # to the widest width — never a fill token, never extra columns.
        section = DocumentSection(
            "D", 1, "", tables=[DocumentTable(rows=[["A", "B", "C"], ["x"]])]
        )
        n = normalize_document(_doc([section]), _PROV)
        block = "| A | B | C |\n| --- | --- | --- |\n| x |  |  |"
        assert block in n.wiki_markdown
        assert "| x |  |  |  |" not in n.wiki_markdown  # no extra columns

    def test_single_row_table_still_has_separator(self):
        section = DocumentSection("D", 1, "", tables=[DocumentTable(rows=[["only"]])])
        n = normalize_document(_doc([section]), _PROV)
        assert "| only |\n| --- |" in n.wiki_markdown

    def test_empty_table_renders_nothing_no_fill_token(self):
        # A table with zero rows contributes no markup and no stray token to
        # the page or the section memory (guards the early-return).
        section = DocumentSection("D", 1, "text", tables=[DocumentTable(rows=[])])
        n = normalize_document(_doc([section]), _PROV)
        assert "## D\n\ntext" in n.wiki_markdown
        assert "XXXX" not in n.wiki_markdown
        assert n.section_memories[0].content == "[D]\n\ntext"

    def test_table_in_section_memory_content(self):
        section = DocumentSection(
            "D", 1, "intro", tables=[DocumentTable(rows=[["A", "B"]])]
        )
        n = normalize_document(_doc([section]), _PROV)
        content = n.section_memories[0].content
        assert content == "[D]\n\nintro\n\n| A | B |\n| --- | --- |"


class TestImageNotice:
    def test_image_count_emits_exact_notice(self):
        n = normalize_document(
            _doc([DocumentSection("H", 1, "b")], image_count=3), _PROV
        )
        assert n.image_count == 3
        expected = (
            "3 embedded image(s) skipped — images are not ingested "
            "(issue #192 non-goal: no OCR/image extraction)."
        )
        assert n.notices == [expected]
        # The notice is followed by a blank spacer line, then the section —
        # pins the spacer as "" (not a fill token).
        assert f"> Note: {expected}\n\n## H\n\nb" in n.wiki_markdown
        assert "XXXX" not in n.wiki_markdown

    def test_zero_images_no_notice(self):
        n = normalize_document(_doc([DocumentSection("H", 1, "b")]), _PROV)
        assert n.notices == []


class TestEmptyDocument:
    def test_empty_document_notice_and_no_section_memories(self):
        n = normalize_document(_doc([DocumentSection("", 0, "")]), _PROV)
        assert n.section_memories == []
        assert n.notices == ["Document contained no extractable text."]
        # The empty notice is the final content — no trailing fill token.
        assert n.wiki_markdown.rstrip().endswith(
            "Document contained no extractable text."
        )
        assert "XXXX" not in n.wiki_markdown

    def test_empty_and_images_both_noticed(self):
        n = normalize_document(_doc([DocumentSection("", 0, "")], image_count=1), _PROV)
        assert len(n.notices) == 2
        assert any("image" in x for x in n.notices)
        assert any("no extractable text" in x for x in n.notices)


class TestSlugify:
    def test_slug_basic(self):
        assert slugify("Hello World!") == "hello-world"

    def test_slug_strips_leading_trailing_separators(self):
        assert slugify("  !Hello!  ") == "hello"

    def test_slug_truncated_to_80(self):
        assert slugify("a" * 200) == "a" * 80

    def test_slug_empty_falls_back(self):
        assert slugify("") == "document"

    def test_slug_all_punctuation_falls_back(self):
        assert slugify("!!!___!!!") == "document"


class TestReturnShape:
    def test_returns_normalized_document(self):
        n = normalize_document(_doc([DocumentSection("H", 1, "b")]), _PROV)
        assert isinstance(n, NormalizedDocument)
        assert n.wiki_markdown.endswith("\n")
        assert n.image_count == 0
