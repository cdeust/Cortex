"""Tests for shared.wiki_classification — the registry-driven 4-tuple schema.

Per user direction 2026-05-12, validation consults
``mcp_server.core.wiki_axis_registry`` rather than hardcoded frozensets.
Tests here exercise the validation contract; tests for the registry
itself live in ``tests_py/core/test_wiki_axis_registry.py``.
"""

from __future__ import annotations

import pytest

from mcp_server.core.wiki_axis_registry import reset_registry
from mcp_server.shared.wiki_classification import (
    Classification,
    Generator,
    all_known_kinds,
    classification_to_frontmatter,
    is_legacy_kind,
    normalize_legacy_kind,
)


@pytest.fixture(autouse=True)
def _fresh_registry():
    """Reset the registry singleton between tests so a stray edit by one
    test cannot leak into another."""
    reset_registry()
    yield
    reset_registry()


# ── Happy path ─────────────────────────────────────────────────────────


def test_minimal_valid_classification() -> None:
    c = Classification(kind="explanation", lifecycle="seedling")
    assert c.kind == "explanation"
    assert c.audience == ("developer",)
    assert c.provenance == "human"


def test_adr_with_proposed_lifecycle() -> None:
    Classification(kind="adr", lifecycle="proposed")


def test_runbook_with_multi_audience() -> None:
    """Audience facet is multi-valued (ADR-2244 §4.3)."""
    c = Classification(
        kind="runbook",
        lifecycle="active",
        audience=("ops", "security"),
    )
    assert c.audience == ("ops", "security")


# ── Lifecycle / kind interaction ───────────────────────────────────────


def test_adr_rejects_universal_lifecycle() -> None:
    """ADR cannot use seedling/draft/active — those don't apply to ``adr``.

    Asserts the ADR-subset list is real registry content (e.g. 'proposed'),
    not an empty list — a mutant that looks the subset up under the wrong
    axis key returns `[]` and would still satisfy a weaker
    "kind=adr requires a lifecycle" substring match (issue #282
    mutation-testing gap).
    """
    with pytest.raises(ValueError) as exc:
        Classification(kind="adr", lifecycle="seedling")
    msg = str(exc.value)
    assert "kind=adr requires a lifecycle from [" in msg
    assert "'proposed'" in msg
    assert "got 'seedling'" in msg


def test_non_adr_rejects_adr_lifecycle() -> None:
    """A how-to cannot be ``proposed`` — that's restricted to kind=adr."""
    with pytest.raises(ValueError, match="does not apply to kind"):
        Classification(kind="how-to", lifecycle="proposed")


# ── Unknown values: reject + suggest ──────────────────────────────────


def test_unknown_kind_rejected_with_suggestion() -> None:
    """Per user direction 2026-05-12: reject + suggest, not warn-and-accept.

    Asserts the exact "Did you mean" phrasing with the bracketed suggestion
    list, not just substring presence of "adr" — the typo'd VALUE itself
    ("adrs") already contains "adr" as a substring, so a weaker assertion
    would pass even if the wrong axis were passed to did_you_mean (issue
    #282 mutation-testing gap: this is a real behavior difference, since a
    wrong axis makes the registry lookup empty and silently falls back to
    the "No close matches" message instead).
    """
    with pytest.raises(ValueError) as exc:
        Classification(kind="adrs", lifecycle="seedling")  # plural typo of 'adr'
    msg = str(exc.value)
    assert "unknown kind: 'adrs'" in msg  # exact value echoed, not swapped for None
    assert "Did you mean one of ['adr']" in msg
    assert "wiki/_schema/kinds" in msg  # extension path mentioned


def test_unknown_audience_rejected_with_extension_hint() -> None:
    with pytest.raises(ValueError) as exc:
        Classification(
            kind="explanation",
            lifecycle="seedling",
            audience=("developper",),  # typo
        )
    msg = str(exc.value)
    assert "unknown audience: 'developper'" in msg  # exact value, not None
    assert "Did you mean one of ['developer']" in msg


def test_unknown_provenance_rejected_with_extension_hint() -> None:
    with pytest.raises(ValueError) as exc:
        Classification(
            kind="explanation",
            lifecycle="seedling",
            provenance="hummman",  # typo
        )
    msg = str(exc.value)
    assert "unknown provenance: 'hummman'" in msg  # exact value, not None
    assert "Did you mean one of ['human']" in msg


def test_unknown_lifecycle_rejected_with_extension_hint() -> None:
    with pytest.raises(ValueError) as exc:
        Classification(kind="explanation", lifecycle="seedlinggg")
    msg = str(exc.value)
    assert "unknown lifecycle: 'seedlinggg'" in msg  # exact value, not None
    assert "Did you mean one of [" in msg
    assert "'seedling'" in msg


def test_completely_unrelated_value_rejected_without_suggestion() -> None:
    """When no close match exists, the error still names the registry path."""
    with pytest.raises(ValueError) as exc:
        Classification(kind="quantum-superposition", lifecycle="seedling")
    msg = str(exc.value)
    assert "unknown kind" in msg
    assert "wiki/_schema/kinds" in msg


# ── Generator requirement is registry-driven ───────────────────────────


def test_provenance_with_requires_generator_demands_generator_block() -> None:
    """``auto-generated`` provenance carries ``requires_generator=True``
    in the registry seed; validation enforces it without hardcoding."""
    with pytest.raises(ValueError, match="requires a Generator block"):
        Classification(
            kind="reference",
            lifecycle="seedling",
            provenance="auto-generated",
        )


def test_ai_generated_with_full_generator_block_accepted() -> None:
    gen = Generator(
        model="claude-opus-4-7",
        version="1.0",
        prompt_template="adr-synthesizer-v1",
        generated_at="2026-05-12T08:55:00Z",
    )
    c = Classification(
        kind="rfc",
        lifecycle="draft",
        provenance="ai-generated",
        generator=gen,
    )
    assert c.generator is not None
    assert c.generator.model == "claude-opus-4-7"


def test_human_provenance_does_not_require_generator() -> None:
    c = Classification(kind="adr", lifecycle="accepted", provenance="human")
    assert c.generator is None


# ── Empty audience guard ───────────────────────────────────────────────


def test_empty_audience_rejected() -> None:
    # Exact-string match (not `pytest.raises(match=...)`, a substring
    # search): a mutant that pads the message with "XX...XX" markers would
    # still satisfy a substring search, since the original text remains
    # contained inside the padded one (issue #282 mutation-testing gap).
    with pytest.raises(ValueError) as exc:
        Classification(kind="explanation", lifecycle="seedling", audience=())
    assert str(exc.value) == "audience must not be empty"


# ── Frontmatter serialization ──────────────────────────────────────────


def test_frontmatter_includes_required_axes() -> None:
    c = Classification(kind="how-to", lifecycle="active", audience=("developer",))
    fm = classification_to_frontmatter(c)
    assert fm["kind"] == "how-to"
    assert fm["lifecycle"] == "active"
    assert fm["audience"] == ["developer"]
    assert fm["provenance"] == "human"


def test_frontmatter_omits_empty_tags() -> None:
    c = Classification(kind="explanation", lifecycle="seedling")
    fm = classification_to_frontmatter(c)
    assert "tags" not in fm


def test_frontmatter_includes_non_empty_tags_under_the_right_key() -> None:
    c = Classification(kind="explanation", lifecycle="seedling", tags=("alpha", "beta"))
    fm = classification_to_frontmatter(c)
    assert fm["tags"] == ["alpha", "beta"]


def test_frontmatter_serializes_generator_block() -> None:
    gen = Generator(
        model="claude-opus-4-7",
        version="1.0",
        prompt_template="codebase-analyze-v1",
        generated_at="2026-05-12T09:00:00Z",
    )
    c = Classification(
        kind="reference",
        lifecycle="seedling",
        provenance="auto-generated",
        generator=gen,
    )
    fm = classification_to_frontmatter(c)
    assert "generator" in fm
    assert fm["generator"] == {
        "model": "claude-opus-4-7",
        "version": "1.0",
        "prompt_template": "codebase-analyze-v1",
        "generated_at": "2026-05-12T09:00:00Z",
    }


# ── Legacy back-compat helpers ─────────────────────────────────────────


def test_normalize_legacy_notes_to_explanation() -> None:
    assert normalize_legacy_kind("notes") == "explanation"


def test_normalize_legacy_specs_to_rfc() -> None:
    assert normalize_legacy_kind("specs") == "rfc"


def test_normalize_modern_kind_unchanged() -> None:
    assert normalize_legacy_kind("adr") == "adr"
    assert normalize_legacy_kind("runbook") == "runbook"


def test_is_legacy_kind() -> None:
    assert is_legacy_kind("notes") is True
    assert is_legacy_kind("adr") is False


def test_all_known_kinds_includes_modern_and_legacy() -> None:
    union = all_known_kinds()
    assert "adr" in union and "runbook" in union  # modern
    assert "notes" in union and "specs" in union  # legacy
