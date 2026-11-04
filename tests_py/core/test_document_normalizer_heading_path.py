"""Section memories are labelled by their full heading path (issue #713).

Repeated text under different parent headings must produce distinguishable
memories, so a recalled segment names where in the document it came from.
"""

from __future__ import annotations

from mcp_server.core.document_model import (
    DocumentProvenance,
    DocumentSection,
    ParsedDocument,
)
from mcp_server.core.document_normalizer import normalize_document

_PROV = DocumentProvenance(
    source="/docs/x.docx", version="deadbeef", source_kind="docx"
)


def _contents(sections: list[DocumentSection]) -> list[str]:
    doc = ParsedDocument(title="Doc", sections=sections)
    return [m.content for m in normalize_document(doc, _PROV).section_memories]


def test_repeated_text_under_different_parents_stays_distinct():
    contents = _contents(
        [
            DocumentSection("Install", 1, "steps a"),
            DocumentSection("Notes", 2, "restart required"),
            DocumentSection("Uninstall", 1, "steps b"),
            DocumentSection("Notes", 2, "restart required"),
        ]
    )
    assert contents == [
        "[Install]\n\nsteps a",
        "[Install > Notes]\n\nrestart required",
        "[Uninstall]\n\nsteps b",
        "[Uninstall > Notes]\n\nrestart required",
    ]


def test_sibling_at_same_level_closes_previous_heading():
    contents = _contents(
        [
            DocumentSection("A", 1, "a"),
            DocumentSection("B", 2, "b"),
            DocumentSection("C", 2, "c"),
            DocumentSection("D", 3, "d"),
            DocumentSection("E", 2, "e"),
        ]
    )
    assert contents == [
        "[A]\n\na",
        "[A > B]\n\nb",
        "[A > C]\n\nc",
        "[A > C > D]\n\nd",
        "[A > E]\n\ne",
    ]


def test_empty_parent_still_names_its_children():
    contents = _contents(
        [DocumentSection("Parent", 1, ""), DocumentSection("Child", 2, "x")]
    )
    assert contents == ["[Parent > Child]\n\nx"]


def test_preamble_keeps_document_body_label_and_no_ancestry():
    contents = _contents(
        [DocumentSection("", 0, "loose"), DocumentSection("H", 1, "h")]
    )
    assert contents == ["[(document body)]\n\nloose", "[H]\n\nh"]


def test_heading_field_stays_the_own_heading():
    doc = ParsedDocument(
        title="Doc",
        sections=[DocumentSection("P", 1, "p"), DocumentSection("C", 2, "c")],
    )
    memories = normalize_document(doc, _PROV).section_memories
    assert [m.heading for m in memories] == ["P", "C"]
