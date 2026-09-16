"""A draft section carries a heading and a body, both text (issue #587).

`_validate_against_contract` checked that the kind's required headings were
present and that each body was non-blank, never that the section's own heading
was. For a kind with no required section, `{"heading": "   ", "body": "..."}`
and `{}` were written straight to the draft, and `wiki_compile` then rendered a
section with no title. The tool schema says a section has both fields, but the
client-visible schema comes from the registered wrapper's signature
(`list[dict[str, Any]] | None`), so the check belongs in the handler.

source: ADR-1070
"""

from __future__ import annotations

import pytest

from mcp_server.handlers.wiki_refine import _validate_against_contract

GOOD = {"heading": "Context", "body": "The forces at play."}


@pytest.mark.parametrize(
    ("section", "expected"),
    [
        ({}, "section 0: heading must be non-blank text"),
        ({"body": "prose"}, "section 0: heading must be non-blank text"),
        ({"heading": "   ", "body": "prose"}, "section 0: heading must be non-blank"),
        ({"heading": 3, "body": "prose"}, "section 0: heading must be non-blank text"),
    ],
    ids=["empty-section", "no-heading", "blank-heading", "heading-not-text"],
)
def test_a_section_without_a_heading_is_refused(section, expected) -> None:
    errors = _validate_against_contract([section], [])

    assert any(expected in error for error in errors), errors


@pytest.mark.parametrize(
    "body",
    [None, "", "   ", 7],
    ids=["no-body", "empty-body", "blank-body", "body-not-text"],
)
def test_a_section_without_a_body_is_refused(body) -> None:
    section = {"heading": "Context"}
    if body is not None:
        section["body"] = body

    errors = _validate_against_contract([section], [])

    assert errors == ["section 'Context' has empty body"]


def test_a_well_formed_section_passes() -> None:
    assert _validate_against_contract([GOOD], []) == []
    assert _validate_against_contract([GOOD], ["Context"]) == []


def test_a_blank_heading_never_satisfies_a_required_section() -> None:
    errors = _validate_against_contract(
        [{"heading": "  ", "body": "prose"}], ["Context"]
    )

    assert "required section missing: 'Context'" in errors
