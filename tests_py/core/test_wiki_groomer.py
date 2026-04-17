"""Tests for the wiki auditor — deterministic drift detection.

Source: docs/program/phase-5-pool-admission-design.md (doc grooming);
user directive "agent or llm on side to write with template and naming
conventions".
"""

from __future__ import annotations

import pytest

from mcp_server.core.wiki_groomer import (
    audit_page,
    audit_wiki,
    infer_kind_from_path,
    parse_frontmatter,
)


class TestFrontmatterParser:
    def test_extracts_keys(self):
        content = "---\ntitle: Foo\nstatus: accepted\n---\n\n# body"
        fm, body = parse_frontmatter(content)
        assert fm == {"title": "Foo", "status": "accepted"}
        assert body.strip() == "# body"

    def test_quoted_values(self):
        content = '---\ntitle: "Foo: Bar"\n---\n'
        fm, _ = parse_frontmatter(content)
        assert fm["title"] == "Foo: Bar"

    def test_no_frontmatter(self):
        content = "# just a heading\n"
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_empty_content(self):
        fm, body = parse_frontmatter("")
        assert fm == {}
        assert body == ""


class TestInferKind:
    @pytest.mark.parametrize(
        "path,expected",
        [
            ("adr/0042-foo.md", "adr"),
            ("specs/phase5.md", "specs"),
            ("lessons/darval-2024.md", "lessons"),
            ("files/src-main-py.md", "files"),
            ("alien/foo.md", None),
            ("foo.md", None),
        ],
    )
    def test_infer(self, path, expected):
        assert infer_kind_from_path(path) == expected


class TestAuditADR:
    CANONICAL_ADR = """---
id: 0042
title: Use lazy heat
status: accepted
date: 2026-04-17
supersedes:
context: We need lazy heat
decision: Switch to effective_heat()
consequences: positive
---

# ADR-0042
"""

    def test_canonical_adr_clean(self):
        audit = audit_page("adr/0042-use-lazy-heat.md", self.CANONICAL_ADR)
        # All required fields present, status valid, slug matches
        # 0042-use-lazy-heat.
        assert not audit.has_issues

    def test_missing_status(self):
        broken = self.CANONICAL_ADR.replace("status: accepted\n", "")
        audit = audit_page("adr/0042-foo.md", broken)
        kinds = {i.kind for i in audit.issues}
        assert "missing_frontmatter" in kinds

    def test_invalid_status(self):
        broken = self.CANONICAL_ADR.replace("status: accepted", "status: underway")
        audit = audit_page("adr/0042-foo.md", broken)
        kinds = {i.kind for i in audit.issues}
        assert "invalid_status" in kinds

    def test_bad_slug(self):
        # Missing 4-digit prefix
        audit = audit_page("adr/use-lazy-heat.md", self.CANONICAL_ADR)
        kinds = {i.kind for i in audit.issues}
        assert "non_canonical_slug" in kinds

    def test_unknown_kind(self):
        audit = audit_page("alien/foo.md", self.CANONICAL_ADR)
        kinds = {i.kind for i in audit.issues}
        assert "unknown_kind" in kinds


class TestManualOverride:
    def test_manual_skips_all_checks(self):
        content = """---
grooming: manual
title: hand-written
---
body
"""
        audit = audit_page("adr/bad-slug.md", content)
        kinds = {i.kind for i in audit.issues}
        assert kinds == {"manual_override"}


class TestSpecAudit:
    def test_missing_required(self):
        minimal = """---
title: Phase 5
---

# Phase 5
"""
        audit = audit_page("specs/phase-5.md", minimal)
        missing = [i for i in audit.issues if i.kind == "missing_frontmatter"]
        assert missing  # status, owner, created, updated all missing


class TestBatchAudit:
    def test_filters_clean_pages(self):
        clean = """---
title: clean notes
updated: 2026-04-17
---

body
"""
        dirty = "# no frontmatter\n"
        results = audit_wiki(
            [
                ("notes/clean.md", clean),
                ("notes/dirty.md", dirty),
            ]
        )
        assert len(results) == 1
        assert results[0].page_path == "notes/dirty.md"
