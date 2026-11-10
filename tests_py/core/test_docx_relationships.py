"""A docx image's relationship id resolves to the part holding its bytes (#732).

source: ECMA-376 Part 2 §9.3 and Annex A.3; issue #732
"""

from __future__ import annotations

import pytest

from mcp_server.core.document_model import DocumentParseError
from mcp_server.core.docx_relationships import parse_docx_relationships

_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _rels(*rels: str) -> str:
    return f'<Relationships xmlns="{_NS}">{"".join(rels)}</Relationships>'


def _rel(rid: str, target: str, mode: str = "") -> str:
    extra = f' TargetMode="{mode}"' if mode else ""
    return f'<Relationship Id="{rid}" Type="t" Target="{target}"{extra}/>'


def test_a_relative_target_resolves_against_the_word_directory():
    xml = _rels(_rel("rId7", "media/image1.png"))
    assert parse_docx_relationships(xml) == {"rId7": "word/media/image1.png"}


@pytest.mark.parametrize(
    ("target", "part"),
    [
        ("/word/media/a.png", "word/media/a.png"),
        ("../media/b.png", "media/b.png"),
        ("./media/./c.png", "word/media/c.png"),
        ("media/x/../d.png", "word/media/d.png"),
        ("../../../e.png", "e.png"),
    ],
)
def test_absolute_and_dot_segment_targets_resolve_per_annex_a3(target, part):
    assert parse_docx_relationships(_rels(_rel("r", target))) == {"r": part}


@pytest.mark.parametrize("target", ["", "/", ".", "..", "./..", "//"])
def test_a_target_that_names_no_part_is_absent(target):
    assert parse_docx_relationships(_rels(_rel("r", target))) == {}


def test_an_external_target_has_no_part_in_the_package():
    xml = _rels(
        _rel("rLink", "https://example.com/a.png", "External"),
        _rel("rIn", "media/b.png", "Internal"),
    )
    assert parse_docx_relationships(xml) == {"rIn": "word/media/b.png"}


def test_a_relationship_without_an_id_is_absent():
    xml = _rels('<Relationship Type="t" Target="media/a.png"/>')
    assert parse_docx_relationships(xml) == {}


def test_an_element_outside_the_package_namespace_is_ignored():
    foreign = '<Relationship xmlns="urn:x" Id="r" Target="a"/>'
    xml = f'<Relationships xmlns="{_NS}">{foreign}</Relationships>'
    assert parse_docx_relationships(xml) == {}


def test_no_relationships_part_resolves_nothing():
    assert parse_docx_relationships("") == {}


def test_malformed_relationships_xml_fails_loudly():
    with pytest.raises(DocumentParseError, match="relationships"):
        parse_docx_relationships("<Relationships")
