"""Unit tests for the pure docx parser (issue #192)."""

from __future__ import annotations

import pytest

from mcp_server.core.docx_parser import parse_docx_xml
from mcp_server.core.document_model import (
    DocumentParseError,
    document_section_is_empty,
    parsed_document_is_empty,
)

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _doc(body: str) -> str:
    return f'<w:document xmlns:w="{_W}"><w:body>{body}</w:body></w:document>'


def _para(text: str, style: str | None = None) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


class TestHeadingsAndBody:
    def test_heading_opens_section_body_attaches(self):
        doc = parse_docx_xml(_doc(_para("Intro", "Heading1") + _para("Body text")))
        headings = [(s.heading, s.level, s.body) for s in doc.sections]
        assert ("Intro", 1, "Body text") in headings

    def test_title_style_sets_title_without_duplicate_section(self):
        doc = parse_docx_xml(
            _doc(_para("My Doc", "Title") + _para("Intro", "Heading1"))
        )
        assert doc.title == "My Doc"
        # The Title text must NOT appear as its own section heading.
        assert all(s.heading != "My Doc" for s in doc.sections)

    def test_title_override_wins(self):
        doc = parse_docx_xml(_doc(_para("First", "Heading1")), title="Override")
        assert doc.title == "Override"

    def test_untitled_fallback(self):
        doc = parse_docx_xml(_doc(_para("plain body")))
        assert doc.title == "Untitled document"

    def test_nested_heading_levels_preserved(self):
        doc = parse_docx_xml(_doc(_para("H1", "Heading1") + _para("H2", "Heading2")))
        levels = {s.heading: s.level for s in doc.sections}
        assert levels["H1"] == 1 and levels["H2"] == 2

    def test_multiple_runs_concatenate(self):
        body = "<w:p><w:r><w:t>Hello </w:t></w:r><w:r><w:t>world</w:t></w:r></w:p>"
        doc = parse_docx_xml(_doc(body))
        assert "Hello world" in doc.sections[0].body


class TestInlineElements:
    def test_tab_becomes_space(self):
        body = "<w:p><w:r><w:t>a</w:t><w:tab/><w:t>b</w:t></w:r></w:p>"
        doc = parse_docx_xml(_doc(body))
        assert doc.sections[0].body == "a b"

    def test_break_becomes_newline(self):
        body = "<w:p><w:r><w:t>a</w:t><w:br/><w:t>b</w:t></w:r></w:p>"
        doc = parse_docx_xml(_doc(body))
        assert doc.sections[0].body == "a\nb"

    def test_empty_text_run_contributes_nothing(self):
        body = "<w:p><w:r><w:t></w:t><w:t>x</w:t></w:r></w:p>"
        doc = parse_docx_xml(_doc(body))
        assert doc.sections[0].body == "x"


class TestTitleDerivation:
    def test_h1_becomes_title_when_no_title_style(self):
        doc = parse_docx_xml(_doc(_para("Report", "Heading1")))
        assert doc.title == "Report"

    def test_h2_does_not_become_title(self):
        # Only Title/Heading1 name the doc; an H2-first doc stays Untitled.
        doc = parse_docx_xml(_doc(_para("Sub", "Heading2")))
        assert doc.title == "Untitled document"

    def test_override_not_overwritten_by_title_paragraph(self):
        doc = parse_docx_xml(
            _doc(_para("DocTitle", "Title") + _para("H", "Heading1")),
            title="Override",
        )
        assert doc.title == "Override"


class TestPreambleHandling:
    def test_leading_body_before_heading_is_kept(self):
        body = _para("preamble text") + _para("H", "Heading1")
        doc = parse_docx_xml(_doc(body))
        assert any("preamble text" in s.body for s in doc.sections)

    def test_empty_preamble_removed_when_headings_present(self):
        doc = parse_docx_xml(_doc(_para("Intro", "Heading1")))
        assert len(doc.sections) == 1
        assert doc.sections[0].heading == "Intro"

    def test_body_only_doc_keeps_single_preamble_section(self):
        doc = parse_docx_xml(_doc(_para("just text")))
        assert len(doc.sections) == 1
        assert doc.sections[0].heading == ""
        assert doc.sections[0].level == 0
        assert doc.sections[0].body == "just text"

    def test_empty_doc_keeps_single_empty_section(self):
        doc = parse_docx_xml(_doc(""))
        assert len(doc.sections) == 1


class TestTables:
    def test_table_extracted_as_rows(self):
        tbl = (
            "<w:tbl>"
            "<w:tr><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc></w:tr>"
            "<w:tr><w:tc><w:p><w:r><w:t>1</w:t></w:r></w:p></w:tc>"
            "<w:tc><w:p><w:r><w:t>2</w:t></w:r></w:p></w:tc></w:tr>"
            "</w:tbl>"
        )
        doc = parse_docx_xml(_doc(_para("Data", "Heading1") + tbl))
        section = next(s for s in doc.sections if s.heading == "Data")
        assert section.tables[0].rows == [["A", "B"], ["1", "2"]]

    def test_multi_paragraph_cell_joined_by_single_space(self):
        tbl = (
            "<w:tbl><w:tr><w:tc>"
            "<w:p><w:r><w:t>line1</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>line2</w:t></w:r></w:p>"
            "</w:tc></w:tr></w:tbl>"
        )
        doc = parse_docx_xml(_doc(_para("H", "Heading1") + tbl))
        section = next(s for s in doc.sections if s.heading == "H")
        assert section.tables[0].rows == [["line1 line2"]]


_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _drawing(rid: str) -> str:
    blip = f'<a:blip xmlns:a="{_A}" xmlns:r="{_R}" r:embed="{rid}"/>'
    return f"<w:p><w:r><w:drawing>{blip}</w:drawing></w:r></w:p>"


class TestImages:
    def test_drawing_inventoried_unsupported(self):
        body = _para("x") + "<w:p><w:r><w:drawing/></w:r></w:p>"
        doc = parse_docx_xml(_doc(body))
        assert [
            (a.ordinal, a.reference, a.section_index, a.state) for a in doc.attachments
        ] == [(1, "", 0, "unsupported")]

    def test_legacy_pict_reference_is_its_imagedata_id(self):
        pict = (
            f'<w:pict><v:imagedata xmlns:v="urn:schemas-microsoft-com:vml" '
            f'xmlns:r="{_R}" r:id="rId9"/></w:pict>'
        )
        doc = parse_docx_xml(_doc(f"<w:p><w:r>{pict}</w:r></w:p>"))
        assert [a.reference for a in doc.attachments] == ["rId9"]

    def test_images_keep_document_order_and_their_section(self):
        body = (
            _drawing("rId1")
            + _para("Design", "Heading1")
            + _drawing("rId2")
            + _para("Rollout", "Heading2")
            + _drawing("rId3")
        )
        doc = parse_docx_xml(_doc(body))
        # The preamble holds an image, so it is kept and the indices stay 0..2.
        assert [
            (a.ordinal, a.reference, doc.sections[a.section_index].heading)
            for a in doc.attachments
        ] == [
            (1, "rId1", ""),
            (2, "rId2", "Design"),
            (3, "rId3", "Rollout"),
        ]
        assert [a.section_index for a in doc.attachments] == [0, 1, 2]

    def test_dropping_an_empty_preamble_shifts_the_section_indices(self):
        body = (
            _para("A", "Heading1")
            + _drawing("rId1")
            + _para("B", "Heading1")
            + _drawing("rId2")
        )
        doc = parse_docx_xml(_doc(body))
        assert [s.heading for s in doc.sections] == ["A", "B"]
        assert [a.section_index for a in doc.attachments] == [0, 1]

    def test_a_picture_hyperlink_is_not_taken_for_the_image(self):
        link = f'<a:hlinkClick xmlns:a="{_A}" xmlns:r="{_R}" r:id="rId8"/>'
        doc_pr = f'<wp:docPr xmlns:wp="urn:wp" id="1" name="p">{link}</wp:docPr>'
        blip = f'<a:blip xmlns:a="{_A}" xmlns:r="{_R}" r:embed="rId5"/>'
        body = f"<w:p><w:r><w:drawing>{doc_pr}{blip}</w:drawing></w:r></w:p>"
        doc = parse_docx_xml(_doc(body))
        assert [a.reference for a in doc.attachments] == ["rId5"]

    def test_a_blip_without_embed_has_an_empty_reference(self):
        blip = f'<a:blip xmlns:a="{_A}"/>'
        doc = parse_docx_xml(
            _doc(f"<w:p><w:r><w:drawing>{blip}</w:drawing></w:r></w:p>")
        )
        assert [a.reference for a in doc.attachments] == [""]

    def test_imagedata_without_id_has_an_empty_reference(self):
        pict = '<w:pict><v:imagedata xmlns:v="urn:schemas-microsoft-com:vml"/></w:pict>'
        doc = parse_docx_xml(_doc(f"<w:p><w:r>{pict}</w:r></w:p>"))
        assert [a.reference for a in doc.attachments] == [""]

    def test_image_inside_a_table_is_inventoried(self):
        tbl = f"<w:tbl><w:tr><w:tc>{_drawing('rId4')}</w:tc></w:tr></w:tbl>"
        doc = parse_docx_xml(_doc(_para("T", "Heading1") + tbl))
        assert [(a.reference, a.section_index) for a in doc.attachments] == [
            ("rId4", 0)
        ]
        assert doc.sections[0].heading == "T"

    def test_no_images_no_attachments(self):
        doc = parse_docx_xml(_doc(_para("x")))
        assert doc.attachments == []


class TestEdgeCases:
    def test_empty_document_is_empty_not_error(self):
        doc = parse_docx_xml(_doc(""))
        assert parsed_document_is_empty(doc)

    def test_headings_only_document(self):
        doc = parse_docx_xml(_doc(_para("A", "Heading1") + _para("B", "Heading1")))
        assert all(document_section_is_empty(s) for s in doc.sections)
        assert [s.heading for s in doc.sections] == ["A", "B"]

    def test_malformed_xml_raises_with_message(self):
        with pytest.raises(DocumentParseError, match="malformed docx XML"):
            parse_docx_xml("<w:document><w:body><unclosed>")

    def test_missing_body_message_exact(self):
        with pytest.raises(DocumentParseError) as exc:
            parse_docx_xml(f'<w:document xmlns:w="{_W}"></w:document>')
        assert str(exc.value) == "docx document.xml has no <w:body>"
