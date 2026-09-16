"""One reading of a draft's sections for every consumer (issue #589).

The Markdown renderer skipped a section with no heading, the `wiki.pages`
mirror kept it under an empty key, and the curator called `.strip()` on
whatever the section held. `shared.wiki_sections` states the shape once.

source: ADR-1071
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from mcp_server.shared.wiki_sections import (
    body_of,
    heading_of,
    is_text,
    titled_sections,
)


@dataclass
class Section:
    """The synthesizer hands objects, not dicts."""

    heading: str
    body: str


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Context", True), ("", False), ("   ", False), (None, False), (3, False)],
    ids=["text", "empty", "blank", "none", "number"],
)
def test_is_text(value, expected) -> None:
    assert is_text(value) is expected


@pytest.mark.parametrize(
    ("section", "expected"),
    [
        ({"heading": "Context"}, "Context"),
        ({"heading": "  Context  "}, "Context"),
        ({}, None),
        ({"heading": ""}, None),
        ({"heading": 3}, None),
        (Section(heading="Context", body="prose"), "Context"),
    ],
    ids=["dict", "padded", "missing", "empty", "number", "object"],
)
def test_heading_of(section, expected) -> None:
    assert heading_of(section) == expected


@pytest.mark.parametrize(
    ("section", "expected"),
    [
        ({"body": "prose"}, "prose"),
        ({}, ""),
        ({"body": "   "}, ""),
        ({"body": 7}, ""),
        (Section(heading="Context", body="prose"), "prose"),
    ],
    ids=["dict", "missing", "blank", "number", "object"],
)
def test_body_of(section, expected) -> None:
    assert body_of(section) == expected


def test_titled_sections_drops_what_a_page_cannot_carry() -> None:
    sections = [
        {"heading": "Context", "body": "prose"},
        {"heading": "   ", "body": "orphan prose"},
        {"body": "no heading at all"},
        {"heading": 3, "body": "not text"},
        Section(heading="Decision", body="the rule"),
    ]

    assert titled_sections(sections) == [
        ("Context", "prose"),
        ("Decision", "the rule"),
    ]


def test_titled_sections_accepts_nothing() -> None:
    assert titled_sections(None) == []
    assert titled_sections([]) == []
