"""Tests for shared.wiki_classification — the ADR-2244 4-tuple schema."""

from __future__ import annotations

import pytest

from mcp_server.shared.wiki_classification import (
    ADR_LIFECYCLES,
    AUDIENCES,
    KINDS,
    LEGACY_KINDS,
    LIFECYCLES,
    PROVENANCES,
    Classification,
    Generator,
    all_known_kinds,
    is_legacy_kind,
    normalize_legacy_kind,
)


# ── Enum integrity ─────────────────────────────────────────────────────


def test_kinds_count_is_eight() -> None:
    """ADR-2244 §4.1: exactly 8 modern kinds."""
    assert len(KINDS) == 8


def test_kinds_match_adr_spec() -> None:
    """Spec match: tutorial, how-to, reference, explanation, adr, runbook, rfc, journal."""
    assert KINDS == {
        "tutorial",
        "how-to",
        "reference",
        "explanation",
        "adr",
        "runbook",
        "rfc",
        "journal",
    }


def test_legacy_kinds_disjoint_from_modern() -> None:
    """ADR-2244 §4.1: legacy kinds (notes, specs, etc.) are not modern."""
    assert KINDS.isdisjoint(LEGACY_KINDS)


def test_adr_lifecycle_disjoint_from_universal_lifecycle() -> None:
    """ADR-2244 §4.2: ADR statuses are a disjoint set, not a subset.

    An ADR can be {proposed, accepted, rejected, superseded}; it cannot be
    {seedling, draft, active, deprecated, archived}.
    """
    assert ADR_LIFECYCLES.isdisjoint(LIFECYCLES)


def test_audiences_closed_enum() -> None:
    """User direction 2026-05-12: closed enum, 5 values."""
    assert AUDIENCES == {"developer", "ops", "security", "internal", "external"}


def test_provenances_closed_enum() -> None:
    assert PROVENANCES == {"human", "ai-generated", "imported", "auto-generated"}


# ── Classification validation ──────────────────────────────────────────


def test_minimal_valid_classification() -> None:
    c = Classification(kind="explanation", lifecycle="seedling")
    assert c.kind == "explanation"
    assert c.audience == ("developer",)
    assert c.provenance == "human"


def test_adr_with_proposed_lifecycle() -> None:
    Classification(kind="adr", lifecycle="proposed")


def test_adr_rejects_universal_lifecycle() -> None:
    """ADR cannot use seedling/draft/active/etc — only its own statuses."""
    with pytest.raises(ValueError, match="invalid lifecycle"):
        Classification(kind="adr", lifecycle="seedling")


def test_non_adr_rejects_adr_lifecycle() -> None:
    """A how-to cannot be 'proposed' — that's an ADR-only status."""
    with pytest.raises(ValueError, match="invalid lifecycle"):
        Classification(kind="how-to", lifecycle="proposed")


def test_unknown_kind_rejected() -> None:
    with pytest.raises(ValueError, match="unknown kind"):
        Classification(kind="notes", lifecycle="seedling")


def test_unknown_audience_rejected() -> None:
    with pytest.raises(ValueError, match="unknown audience"):
        Classification(
            kind="explanation",
            lifecycle="seedling",
            audience=("data-scientist",),  # not in closed enum
        )


def test_empty_audience_rejected() -> None:
    with pytest.raises(ValueError, match="audience must not be empty"):
        Classification(kind="explanation", lifecycle="seedling", audience=())


def test_multi_valued_audience_accepted() -> None:
    """Audience facet is multi-valued (ADR-2244 §4.3)."""
    c = Classification(
        kind="runbook",
        lifecycle="active",
        audience=("ops", "security"),
    )
    assert c.audience == ("ops", "security")


def test_ai_generated_requires_generator_block() -> None:
    """User direction 2026-05-12: full provenance block for ai-generated."""
    with pytest.raises(ValueError, match="requires a Generator block"):
        Classification(
            kind="explanation",
            lifecycle="seedling",
            provenance="ai-generated",
        )


def test_auto_generated_requires_generator_block() -> None:
    with pytest.raises(ValueError, match="requires a Generator block"):
        Classification(
            kind="reference",
            lifecycle="seedling",
            provenance="auto-generated",
        )


def test_human_provenance_does_not_require_generator() -> None:
    c = Classification(
        kind="adr",
        lifecycle="accepted",
        provenance="human",
    )
    assert c.generator is None


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


# ── Frontmatter serialization ──────────────────────────────────────────


def test_frontmatter_includes_required_axes() -> None:
    c = Classification(kind="how-to", lifecycle="active", audience=("developer",))
    fm = c.to_frontmatter()
    assert fm["kind"] == "how-to"
    assert fm["lifecycle"] == "active"
    assert fm["audience"] == ["developer"]
    assert fm["provenance"] == "human"


def test_frontmatter_omits_empty_tags() -> None:
    c = Classification(kind="explanation", lifecycle="seedling")
    fm = c.to_frontmatter()
    assert "tags" not in fm


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
    fm = c.to_frontmatter()
    assert "generator" in fm
    assert fm["generator"] == {
        "model": "claude-opus-4-7",
        "version": "1.0",
        "prompt_template": "codebase-analyze-v1",
        "generated_at": "2026-05-12T09:00:00Z",
    }


# ── Legacy helpers ─────────────────────────────────────────────────────


def test_normalize_legacy_notes_to_explanation() -> None:
    assert normalize_legacy_kind("notes") == "explanation"


def test_normalize_legacy_specs_to_rfc() -> None:
    assert normalize_legacy_kind("specs") == "rfc"


def test_normalize_legacy_lessons_to_explanation() -> None:
    assert normalize_legacy_kind("lessons") == "explanation"


def test_normalize_modern_kind_unchanged() -> None:
    assert normalize_legacy_kind("adr") == "adr"
    assert normalize_legacy_kind("runbook") == "runbook"


def test_is_legacy_kind() -> None:
    assert is_legacy_kind("notes") is True
    assert is_legacy_kind("specs") is True
    assert is_legacy_kind("adr") is False
    assert is_legacy_kind("how-to") is False


def test_all_known_kinds_is_union() -> None:
    """Used by read paths that must accept either legacy or modern frontmatter."""
    union = all_known_kinds()
    assert KINDS.issubset(union)
    assert LEGACY_KINDS.issubset(union)
