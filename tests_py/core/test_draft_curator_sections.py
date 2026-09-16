"""The curator reads a draft's sections without assuming their shape (#589).

`_missing_required_sections` called `.strip()` on whatever a section held, so
a heading that was not text raised `AttributeError` inside `evaluate_draft`,
and a `Section` object with an empty heading raised on the `.get` fallback.

source: ADR-1071
"""

from __future__ import annotations

import pytest

from mcp_server.core.draft_curator import evaluate_draft
from mcp_server.shared.wiki_schema_loader import KindDefinition

FILLED = "Prose long enough to count as a filled section."


def _kind(required: tuple[str, ...]) -> KindDefinition:
    return KindDefinition(
        name="adr",
        display_name="ADR",
        dir_name="adr",
        required_sections=list(required),
    )


def _draft(sections: list) -> dict:
    return {
        "confidence": 0.9,
        "title": "A settled decision",
        "lead": "What was decided and why.",
        "sections": sections,
    }


@pytest.mark.parametrize(
    "section",
    [
        {"heading": 3, "body": FILLED},
        {"body": FILLED},
        {"heading": "   ", "body": FILLED},
        {},
    ],
    ids=["heading-not-text", "no-heading", "blank-heading", "empty-section"],
)
def test_a_malformed_section_is_reported_not_raised(section) -> None:
    decision = evaluate_draft(_draft([section]), _kind(("Context",)))

    assert decision.verdict != "approved"
    assert any("missing required sections" in reason for reason in decision.reasons)


def test_a_well_formed_section_still_satisfies_its_requirement() -> None:
    decision = evaluate_draft(
        _draft([{"heading": "Context", "body": FILLED}]), _kind(("Context",))
    )

    assert decision.verdict == "approved"
    assert decision.reasons == ()
