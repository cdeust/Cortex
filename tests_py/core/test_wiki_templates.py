"""Tests for wiki_templates — coherence between PAGE_KINDS and templates.

Source: docs/program/phase-5-pool-admission-design.md (doc grooming);
user directive "template and naming conventions".
"""

from __future__ import annotations

import re

from mcp_server.core.wiki_layout import PAGE_KINDS
from mcp_server.core.wiki_templates import (
    REQUIRED_FRONTMATTER,
    STATUS_VALUES,
    TEMPLATES,
    naming_convention,
    required_fields,
    template_for,
    valid_status_values,
)


class TestTemplateCoverage:
    def test_every_page_kind_has_template(self):
        for kind in PAGE_KINDS:
            assert template_for(kind) is not None, f"missing template: {kind}"

    def test_every_page_kind_has_required_fields(self):
        for kind in PAGE_KINDS:
            assert required_fields(kind), f"no required fields for {kind}"

    def test_unknown_kind_returns_none_template(self):
        assert template_for("alien-kind") is None

    def test_unknown_kind_returns_default_required(self):
        # Default is a sensible minimum
        fields = required_fields("alien-kind")
        assert "title" in fields


class TestTemplateBodies:
    def test_adr_contains_status_and_consequences(self):
        t = TEMPLATES["adr"]
        assert "{{status}}" in t
        assert "## Consequences" in t
        assert "## Context" in t
        assert "## Decision" in t

    def test_spec_contains_core_sections(self):
        t = TEMPLATES["specs"]
        for section in ("## Problem", "## Goals", "## Non-goals", "## Invariants"):
            assert section in t

    def test_lesson_contains_rule(self):
        t = TEMPLATES["lessons"]
        assert "## Rule going forward" in t
        assert "## Why it went wrong" in t


class TestStatusValues:
    def test_adr_has_valid_statuses(self):
        values = valid_status_values("adr")
        assert "proposed" in values
        assert "accepted" in values
        assert "superseded" in values

    def test_non_status_kinds_return_empty(self):
        # Guides / reference / conventions don't have status fields.
        assert valid_status_values("guides") == ()
        assert valid_status_values("notes") == ()


class TestNamingConvention:
    def test_adr_pattern_matches_canonical(self):
        pattern, _ = naming_convention("adr")
        assert re.match(pattern, "0042-prefer-plan-over-list")
        assert re.match(pattern, "0001-foo")

    def test_adr_pattern_rejects_wrong_shape(self):
        pattern, _ = naming_convention("adr")
        # Missing 4-digit prefix
        assert not re.match(pattern, "prefer-plan-over-list")
        # Uppercase
        assert not re.match(pattern, "0042-Prefer-Plan")
        # Underscores
        assert not re.match(pattern, "0042_prefer_plan")

    def test_spec_pattern_matches_kebab(self):
        pattern, _ = naming_convention("specs")
        assert re.match(pattern, "phase-5-pool-admission-design")
        assert re.match(pattern, "ingest-pipeline")

    def test_default_pattern_rejects_underscores(self):
        pattern, _ = naming_convention("guides")
        assert re.match(pattern, "how-to-run-benchmarks")
        assert not re.match(pattern, "how_to_run_benchmarks")


class TestPlaceholderConsistency:
    """Placeholders referenced in templates must match front-matter schema."""

    def test_adr_placeholders_cover_required_fields(self):
        t = TEMPLATES["adr"]
        for field in REQUIRED_FRONTMATTER["adr"]:
            # Allow field to appear in template body OR as {{placeholder}}.
            assert f"{{{{{field}}}}}" in t or field in t, (
                f"ADR required field {field!r} missing from template"
            )
