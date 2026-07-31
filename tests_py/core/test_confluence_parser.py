"""Unit tests for the pure Confluence storage-format parser (issue #192)."""

from __future__ import annotations

import pytest

from mcp_server.core.confluence_parser import parse_confluence_storage
from mcp_server.core.document_model import (
    DocumentParseError,
    document_section_is_empty,
    parsed_document_is_empty,
)


class TestHeadingsAndBody:
    def test_heading_opens_section(self):
        doc = parse_confluence_storage("<h1>Intro</h1><p>Body</p>")
        section = next(s for s in doc.sections if s.heading == "Intro")
        assert section.body == "Body"

    def test_first_heading_sets_title(self):
        doc = parse_confluence_storage("<h1>Page Title</h1><p>x</p>")
        assert doc.title == "Page Title"

    def test_title_override_wins(self):
        doc = parse_confluence_storage("<h1>Ignored</h1>", title="Override")
        assert doc.title == "Override"

    def test_untitled_fallback(self):
        doc = parse_confluence_storage("<p>no heading</p>")
        assert doc.title == "Untitled page"

    def test_heading_levels_preserved(self):
        doc = parse_confluence_storage("<h2>Sub</h2>")
        assert doc.sections[0].level == 2


class TestEntities:
    def test_named_entities_resolved(self):
        doc = parse_confluence_storage("<p>a&nbsp;b&mdash;c</p>")
        body = doc.sections[0].body
        # No raw entity text survives; whitespace collapsed; mdash present.
        assert "&nbsp;" not in body and "&mdash;" not in body
        assert "—" in body
        assert body.replace(" ", " ") == "a b—c"

    def test_xml_builtin_entities_preserved(self):
        doc = parse_confluence_storage("<p>a &amp; b &lt; c</p>")
        assert "a & b < c" in doc.sections[0].body

    def test_unknown_entity_left_intact_then_fails_loud(self):
        # An entity that is neither an XML builtin nor a known HTML5 name is
        # NOT silently dropped — it is left in place so the XML parser rejects
        # it loudly (exercises the `else: keep` branch of _resolve_entities).
        with pytest.raises(DocumentParseError):
            parse_confluence_storage("<p>a&definitelynotanentity;b</p>")


class TestTextExtraction:
    def test_internal_whitespace_collapsed_to_single_space(self):
        doc = parse_confluence_storage("<p>a   b\t c</p>")
        assert doc.sections[0].body == "a b c"

    def test_text_across_child_elements_concatenated(self):
        doc = parse_confluence_storage("<p>a<strong>b</strong>c</p>")
        assert doc.sections[0].body == "abc"


class TestPreambleAndTitle:
    def test_body_only_fragment_keeps_single_level0_section(self):
        doc = parse_confluence_storage("<p>loose text</p>")
        assert len(doc.sections) == 1
        assert doc.sections[0].heading == ""
        assert doc.sections[0].level == 0
        assert doc.sections[0].body == "loose text"

    def test_leading_body_before_heading_is_kept(self):
        doc = parse_confluence_storage("<p>intro para</p><h1>H</h1>")
        assert any("intro para" in s.body for s in doc.sections)

    def test_empty_fragment_keeps_single_section(self):
        doc = parse_confluence_storage("")
        assert len(doc.sections) == 1

    def test_empty_preamble_removed_when_heading_present(self):
        doc = parse_confluence_storage("<h1>Only</h1>")
        assert len(doc.sections) == 1
        assert doc.sections[0].heading == "Only"


class TestNamespaces:
    def test_ac_namespace_image_counted(self):
        xhtml = '<p>x</p><ac:image><ri:attachment ri:filename="a.png"/></ac:image>'
        doc = parse_confluence_storage(xhtml)
        assert doc.image_count == 1

    def test_plain_img_counted(self):
        doc = parse_confluence_storage('<p>x</p><img src="a.png"/>')
        assert doc.image_count == 1


class TestTables:
    def test_table_extracted(self):
        xhtml = (
            "<h1>D</h1><table><tbody>"
            "<tr><th>H1</th><th>H2</th></tr>"
            "<tr><td>a</td><td>b</td></tr>"
            "</tbody></table>"
        )
        doc = parse_confluence_storage(xhtml)
        section = next(s for s in doc.sections if s.heading == "D")
        assert section.tables[0].rows == [["H1", "H2"], ["a", "b"]]


class TestEdgeCases:
    def test_empty_is_empty(self):
        doc = parse_confluence_storage("")
        assert parsed_document_is_empty(doc)

    def test_headings_only(self):
        doc = parse_confluence_storage("<h1>A</h1><h2>B</h2>")
        assert all(document_section_is_empty(s) for s in doc.sections)

    def test_malformed_xhtml_raises_with_message(self):
        with pytest.raises(DocumentParseError, match="malformed Confluence XHTML"):
            parse_confluence_storage("<h1>Unclosed<p>text")

    def test_doctype_declaration_is_refused(self):
        """S314 entity-expansion/XXE guard (document_model.reject_doctype):
        a DOCTYPE with a custom internal-subset entity must never reach
        ET.fromstring, regardless of well-formedness."""
        bomb = '<!DOCTYPE html [<!ENTITY lol "lol">]><h1>&lol;</h1>'
        with pytest.raises(DocumentParseError, match="DOCTYPE"):
            parse_confluence_storage(bomb)

    def test_doctype_case_insensitive_is_refused(self):
        with pytest.raises(DocumentParseError, match="DOCTYPE"):
            parse_confluence_storage("<!doctype html><h1>x</h1>")
