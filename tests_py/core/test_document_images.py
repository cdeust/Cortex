"""Image inventory: one entry per image, linear in the input (issue #732)."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from mcp_server.core.confluence_parser import parse_confluence_storage
from mcp_server.core.document_images import ImageMarkup, collect_images
from mcp_server.core.document_model import DocumentAttachment
from mcp_server.core.docx_parser import parse_docx_xml

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_V = "urn:schemas-microsoft-com:vml"


def _docx(run: str):
    body = f"<w:body><w:p><w:r>{run}</w:r></w:p></w:body>"
    return parse_docx_xml(f'<w:document xmlns:w="{_W}">{body}</w:document>')


def _imagedata(rid: str) -> str:
    return f'<v:imagedata xmlns:v="{_V}" xmlns:r="{_R}" r:id="{rid}"/>'


def _refs(doc) -> list[tuple[int, str]]:
    return [(a.ordinal, a.reference) for a in doc.attachments]


def test_every_picture_of_a_group_is_inventoried():
    group = (
        f'<v:group xmlns:v="{_V}">{_imagedata("rId1")}{_imagedata("rId2")}</v:group>'
    )
    assert _refs(_docx(f"<w:pict>{group}</w:pict>")) == [(1, "rId1"), (2, "rId2")]


def test_nested_containers_around_one_reference_yield_one_entry():
    depth = 2000
    run = "<w:pict>" * depth + _imagedata("rId7") + "</w:pict>" * depth
    assert _refs(_docx(run)) == [(1, "rId7")]


def test_nested_empty_containers_yield_one_empty_entry():
    assert _refs(_docx("<w:pict><w:pict/></w:pict>")) == [(1, "")]


def test_a_reference_outside_any_container_is_not_an_image():
    assert _docx(_imagedata("rId3")).attachments == []


def test_nested_confluence_images_around_one_attachment_yield_one_entry():
    inner = '<ri:attachment ri:filename="a.png"/>'
    xhtml = "<ac:image>" * 500 + inner + "</ac:image>" * 500
    assert _refs(parse_confluence_storage(xhtml)) == [(1, "a.png")]


def test_a_confluence_attachment_link_outside_an_image_is_not_an_image():
    xhtml = '<p><ac:link><ri:attachment ri:filename="spec.pdf"/></ac:link></p>'
    assert parse_confluence_storage(xhtml).attachments == []


def test_an_img_inside_an_ac_image_is_one_image():
    doc = parse_confluence_storage('<ac:image><img src="x.png"/></ac:image>')
    assert _refs(doc) == [(1, "x.png")]


def test_two_references_in_one_ac_image_are_two_entries():
    xhtml = (
        '<ac:image><ri:attachment ri:filename="a.png"/>'
        '<ri:url ri:value="https://h/b.png"/></ac:image>'
    )
    assert _refs(parse_confluence_storage(xhtml)) == [
        (1, "a.png"),
        (2, "https://h/b.png"),
    ]


def test_a_standalone_img_after_an_empty_ac_image_is_its_own_entry():
    doc = parse_confluence_storage('<ac:image/><img src="b.png"/>')
    assert _refs(doc) == [(1, ""), (2, "b.png")]


def test_each_container_takes_its_own_first_reference():
    first = f"<w:pict>{_imagedata('rId1')}</w:pict>"
    third = f"<w:pict>{_imagedata('rId3')}</w:pict>"
    run = first + "<w:pict/>" + third
    assert _refs(_docx(run)) == [(1, "rId1"), (2, ""), (3, "rId3")]


def test_collect_images_numbers_after_existing_entries_and_tags_the_section():
    markup = ImageMarkup(
        containers=frozenset({"box"}),
        leaves={"pic": "ref", "loose": "ref"},
        standalone=frozenset({"loose"}),
    )
    elem = ET.fromstring(
        '<root><box><pic ref="a"/></box><pic ref="ignored"/><loose ref="b"/></root>'
    )
    out = [DocumentAttachment(1, "earlier", 0)]
    collect_images(elem, 3, markup, out)
    assert [(a.ordinal, a.reference, a.section_index) for a in out] == [
        (1, "earlier", 0),
        (2, "a", 3),
        (3, "b", 3),
    ]


def test_a_leaf_without_its_attribute_has_an_empty_reference():
    doc = parse_confluence_storage("<ac:image><ri:attachment/></ac:image><img/>")
    assert _refs(doc) == [(1, ""), (2, "")]
