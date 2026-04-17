"""Tests for wiki_readme — plain-language top-level README generation.

Source: user directive "readable by non tech while having all
information needed for tech people".
"""

from __future__ import annotations

from datetime import datetime, timezone


from mcp_server.core.wiki_readme import (
    _count_by_domain,
    _count_pages,
    build_plain_readme,
)


_FIXED_TIME = datetime(2026, 4, 17, 14, 30, tzinfo=timezone.utc)


class TestCounts:
    def test_count_pages_by_kind(self):
        paths = [
            "adr/0001-foo.md",
            "adr/0002-bar.md",
            "specs/phase5.md",
            "notes/x.md",
            "alien/wrong.md",  # unknown kind — excluded
        ]
        assert _count_pages(paths) == {"adr": 2, "specs": 1, "notes": 1}

    def test_count_by_domain_skips_root_level(self):
        paths = [
            "adr/cortex/0001.md",
            "adr/cortex/0002.md",
            "specs/cortex/phase5.md",
            "adr/flat.md",  # no domain in path
            "notes/other-domain/x.md",
        ]
        counts = _count_by_domain(paths)
        assert counts["cortex"] == 3
        assert counts["other-domain"] == 1
        assert "flat.md" not in counts


class TestReadmeStructure:
    def test_readme_has_top_heading(self):
        out = build_plain_readme(["adr/0001-foo.md"], generated_at=_FIXED_TIME)
        assert "# Cortex Wiki" in out

    def test_custom_project_name(self):
        out = build_plain_readme([], project_name="MyProject", generated_at=_FIXED_TIME)
        assert "# MyProject Wiki" in out

    def test_plain_language_intro(self):
        """Non-tech readers see a living knowledge base pitch, not jargon."""
        out = build_plain_readme(["adr/0001-foo.md"], generated_at=_FIXED_TIME)
        assert "living knowledge base" in out
        # No jargon gate-keepers
        assert "architecture decision record" not in out.lower()
        assert "immutable" not in out.lower()

    def test_page_count_displayed(self):
        paths = ["adr/0001-foo.md", "adr/0002-bar.md", "specs/x.md"]
        out = build_plain_readme(paths, generated_at=_FIXED_TIME)
        assert "3 pages" in out

    def test_zero_pages_singular_grammar(self):
        out = build_plain_readme([], generated_at=_FIXED_TIME)
        assert "0 pages" in out

    def test_one_page_singular_grammar(self):
        out = build_plain_readme(["adr/0001-foo.md"], generated_at=_FIXED_TIME)
        assert "1 page" in out
        assert "1 pages" not in out

    def test_timestamp_included(self):
        out = build_plain_readme([], generated_at=_FIXED_TIME)
        assert "2026-04-17 14:30 UTC" in out

    def test_links_to_detailed_index(self):
        out = build_plain_readme(["adr/0001-foo.md"], generated_at=_FIXED_TIME)
        assert ".generated/INDEX.md" in out

    def test_only_populated_kinds_rendered(self):
        """A category with 0 pages does NOT appear in the README — we
        don't want a wall of empty sections for a fresh wiki."""
        out = build_plain_readme(["adr/0001-foo.md"], generated_at=_FIXED_TIME)
        assert "Architecture Decisions" in out
        assert "Lessons Learned" not in out  # no lessons pages
        assert "File Documentation" not in out

    def test_domains_section_only_when_domains_present(self):
        # Flat paths (no domain) → no domains section
        out = build_plain_readme(["adr/flat.md"], generated_at=_FIXED_TIME)
        assert "Covered domains" not in out

        # Domain-scoped paths → section appears
        out = build_plain_readme(["adr/cortex/0001.md"], generated_at=_FIXED_TIME)
        assert "Covered domains" in out
        assert "cortex" in out


class TestStability:
    def test_same_input_same_output(self):
        paths = ["adr/0001-foo.md", "specs/x.md"]
        out1 = build_plain_readme(paths, generated_at=_FIXED_TIME)
        out2 = build_plain_readme(paths, generated_at=_FIXED_TIME)
        assert out1 == out2

    def test_kind_order_deterministic(self):
        """Kinds appear in PAGE_KINDS order, not dict-iteration order."""
        # Paths shuffled — output should still put adr before specs.
        paths = ["specs/x.md", "adr/0001-foo.md", "notes/y.md"]
        out = build_plain_readme(paths, generated_at=_FIXED_TIME)
        adr_pos = out.index("Architecture Decisions")
        specs_pos = out.index("Specifications & Designs")
        notes_pos = out.index("Notes & Investigations")
        assert adr_pos < specs_pos < notes_pos


class TestGroomerMention:
    def test_readme_tells_users_about_manual_override(self):
        """Tech readers need to know how to opt a page out of grooming."""
        out = build_plain_readme([], generated_at=_FIXED_TIME)
        assert "grooming: manual" in out
        assert "without your consent" in out
