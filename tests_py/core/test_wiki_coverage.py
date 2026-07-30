"""Tests for wiki_coverage — per-domain scope audit."""

from __future__ import annotations

import os

import pytest

from mcp_server.core.wiki_coverage import (
    SCOPES,
    DomainCoverage,
    ScopeCoverage,
    audit_all_domains,
    audit_domain,
    audit_files,
    domain_coverage_covered_count,
    domain_coverage_coverage_ratio,
    domain_coverage_missing_count,
    domain_coverage_missing_scopes,
    file_coverage_coverage_ratio,
    list_domains,
    list_source_files,
)


_SUBSTANTIVE = "x" * 900  # ≥ _MIN_PAGE_BYTES (800)
_STUB = "x" * 100


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class TestListDomains:
    def test_returns_empty_on_missing_root(self, tmp_path):
        missing = str(tmp_path / "nope")
        assert list_domains(missing) == []

    def test_discovers_domain_present_in_two_kinds(self, tmp_path):
        wiki = str(tmp_path)
        _write(os.path.join(wiki, "reference", "myproj", "x.md"), "a")
        _write(os.path.join(wiki, "notes", "myproj", "y.md"), "a")
        assert "myproj" in list_domains(wiki)

    def test_skips_single_kind_domain(self, tmp_path):
        wiki = str(tmp_path)
        _write(os.path.join(wiki, "reference", "lonely", "x.md"), "a")
        assert "lonely" not in list_domains(wiki)

    def test_filters_underscore_buckets(self, tmp_path):
        wiki = str(tmp_path)
        _write(os.path.join(wiki, "reference", "_general", "x.md"), "a")
        _write(os.path.join(wiki, "notes", "_general", "y.md"), "a")
        assert "_general" not in list_domains(wiki)

    def test_filters_bare_year_buckets(self, tmp_path):
        """A bare 4-digit year is a time bucket, not a project."""
        wiki = str(tmp_path)
        _write(os.path.join(wiki, "reference", "2026", "x.md"), "a")
        _write(os.path.join(wiki, "notes", "2026", "y.md"), "a")
        assert "2026" not in list_domains(wiki)


class TestAuditDomain:
    def test_returns_all_six_scopes(self, tmp_path):
        c = audit_domain(str(tmp_path), "fresh")
        assert len(c.scopes) == len(SCOPES)
        scope_names = {s.scope.name for s in c.scopes}
        assert scope_names == {s.name for s in SCOPES}

    def test_fresh_domain_has_zero_coverage(self, tmp_path):
        c = audit_domain(str(tmp_path), "fresh")
        assert domain_coverage_covered_count(c) == 0
        assert domain_coverage_missing_count(c) == len(SCOPES)
        assert pytest.approx(domain_coverage_coverage_ratio(c), abs=1e-9) == 0.0

    def test_substantive_architecture_anchor_counts(self, tmp_path):
        wiki = str(tmp_path)
        _write(
            os.path.join(wiki, "reference", "p", "architecture-overview.md"),
            _SUBSTANTIVE,
        )
        c = audit_domain(wiki, "p")
        arch = next(s for s in c.scopes if s.scope.name == "architecture")
        assert arch.covered is True
        assert arch.anchor_page == "reference/p/architecture-overview.md"

    def test_stub_does_not_count_as_coverage(self, tmp_path):
        wiki = str(tmp_path)
        _write(
            os.path.join(wiki, "reference", "p", "architecture-overview.md"),
            _STUB,
        )
        c = audit_domain(wiki, "p")
        arch = next(s for s in c.scopes if s.scope.name == "architecture")
        assert arch.covered is False

    def test_decisions_scope_counted_by_any_substantive_adr(self, tmp_path):
        wiki = str(tmp_path)
        # Decisions has no anchor filename — any substantive ADR counts.
        _write(os.path.join(wiki, "adr", "p", "0001-foo.md"), _SUBSTANTIVE)
        c = audit_domain(wiki, "p")
        dec = next(s for s in c.scopes if s.scope.name == "decisions")
        assert dec.covered is True
        assert dec.page_count >= 1

    def test_suggested_path_uses_primary_directory(self, tmp_path):
        c = audit_domain(str(tmp_path), "fresh")
        arch = next(s for s in c.scopes if s.scope.name == "architecture")
        assert arch.suggested_path == "reference/fresh/architecture-overview.md"
        ops = next(s for s in c.scopes if s.scope.name == "operations")
        assert ops.suggested_path == "runbook/fresh/operations.md"


class TestAnchorFreshness:
    """Existing anchor pages older than max_age_days re-enter the queue.

    Source: user direction 2026-05-18 — existing pages should be
    processed the same way as new ones, with no human in the loop.
    """

    def test_fresh_anchor_counts_as_covered(self, tmp_path):
        wiki = str(tmp_path)
        _write(
            os.path.join(wiki, "reference", "p", "architecture-overview.md"),
            _SUBSTANTIVE,
        )
        c = audit_domain(wiki, "p", max_age_days=90)
        arch = next(s for s in c.scopes if s.scope.name == "architecture")
        assert arch.covered is True

    def test_stale_anchor_counts_as_missing(self, tmp_path):
        """An anchor page older than max_age_days re-enters the queue."""
        import os as _os
        import time

        wiki = str(tmp_path)
        anchor = os.path.join(wiki, "reference", "p", "architecture-overview.md")
        _write(anchor, _SUBSTANTIVE)
        # Backdate the file by 120 days.
        old = time.time() - 120 * 86400
        _os.utime(anchor, (old, old))
        c = audit_domain(wiki, "p", max_age_days=90)
        arch = next(s for s in c.scopes if s.scope.name == "architecture")
        assert arch.covered is False
        assert arch.anchor_page is None  # treated as if it didn't exist

    def test_max_age_none_disables_freshness(self, tmp_path):
        """Pass max_age_days=None to fall back to legacy 'any anchor counts'."""
        import os as _os
        import time

        wiki = str(tmp_path)
        anchor = os.path.join(wiki, "reference", "p", "architecture-overview.md")
        _write(anchor, _SUBSTANTIVE)
        old = time.time() - 500 * 86400
        _os.utime(anchor, (old, old))
        c = audit_domain(wiki, "p", max_age_days=None)
        arch = next(s for s in c.scopes if s.scope.name == "architecture")
        assert arch.covered is True


class TestAuditAllDomains:
    def test_audits_each_discovered_domain(self, tmp_path):
        wiki = str(tmp_path)
        for d in ("alpha", "beta"):
            _write(os.path.join(wiki, "reference", d, "x.md"), _SUBSTANTIVE)
            _write(os.path.join(wiki, "notes", d, "y.md"), _SUBSTANTIVE)
        rolls = audit_all_domains(wiki)
        names = {r.domain for r in rolls}
        assert names == {"alpha", "beta"}

    def test_sorted_by_missing_count_desc(self, tmp_path):
        wiki = str(tmp_path)
        # alpha: 1 anchor → 5 missing
        _write(
            os.path.join(wiki, "reference", "alpha", "architecture-overview.md"),
            _SUBSTANTIVE,
        )
        _write(os.path.join(wiki, "notes", "alpha", "y.md"), _SUBSTANTIVE)
        # beta: 0 anchors → 6 missing
        _write(os.path.join(wiki, "reference", "beta", "x.md"), _SUBSTANTIVE)
        _write(os.path.join(wiki, "notes", "beta", "y.md"), _SUBSTANTIVE)
        rolls = audit_all_domains(wiki)
        assert rolls[0].domain == "beta"  # more missing first
        assert rolls[1].domain == "alpha"


class TestListSourceFiles:
    def test_includes_source_extensions(self, tmp_path):
        _write(os.path.join(str(tmp_path), "src", "main.py"), "print(1)")
        _write(os.path.join(str(tmp_path), "src", "lib.ts"), "export {}")
        _write(os.path.join(str(tmp_path), "README.md"), "# doc")
        files = set(list_source_files(str(tmp_path)))
        assert "src/main.py" in files
        assert "src/lib.ts" in files
        assert "README.md" not in files  # .md is documentation, not source

    def test_skips_vendored_dirs(self, tmp_path):
        _write(os.path.join(str(tmp_path), "src", "main.py"), "x")
        _write(os.path.join(str(tmp_path), "node_modules", "lib.js"), "x")
        _write(os.path.join(str(tmp_path), ".git", "x.py"), "x")
        files = set(list_source_files(str(tmp_path)))
        assert "src/main.py" in files
        assert all("node_modules" not in f for f in files)
        assert all(".git" not in f for f in files)


class TestFileCoverage:
    def test_uncovered_files_reported(self, tmp_path, monkeypatch):
        """A file with no wiki mention is counted as uncovered."""
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        src = tmp_path / "src"
        src.mkdir()
        (src / "main.py").write_text("x")
        (src / "lib.py").write_text("x")
        # Wiki references only main.py
        (wiki / "reference").mkdir()
        (wiki / "reference" / "p").mkdir()
        (wiki / "reference" / "p" / "arch.md").write_text(
            "# Architecture\n\nThe entry point is `src/main.py`.\n"
        )
        # Stub the source-root lookup so the test bypasses git discovery.
        monkeypatch.setattr(
            "mcp_server.core.wiki_coverage._project_source_root",
            lambda d: str(src) if d == "p" else None,
        )
        c = audit_files(str(wiki), "p")
        assert c.source_file_count == 2
        assert c.covered_file_count == 1
        assert "lib.py" in c.uncovered_files
        # 1/2 = 0.5: distinguishes division from multiplication (issue #282
        # mutation-testing gap — the vacuous 0/1-only cases elsewhere in
        # this file can't tell `/` from `*` apart).
        assert file_coverage_coverage_ratio(c) == 0.5

    def test_unknown_domain_returns_zero(self, tmp_path, monkeypatch):
        """A domain not tied to a git repo gets a zero-file roll, not a crash."""
        wiki = tmp_path / "wiki"
        wiki.mkdir()
        monkeypatch.setattr(
            "mcp_server.core.wiki_coverage._project_source_root",
            lambda d: None,
        )
        c = audit_files(str(wiki), "ghost")
        assert c.source_root is None
        assert c.source_file_count == 0
        assert file_coverage_coverage_ratio(c) == 1.0  # vacuous coverage


class TestDomainCoverageFreeFunctions:
    """Direct unit tests for the domain_coverage_* free functions (issue
    #282: dataclass mutation blindspot). Constructs DomainCoverage/
    ScopeCoverage directly rather than through audit_domain so the case
    with a NON-vacuous, partial ratio (needed to distinguish `/` from `*`,
    and `sum(1 ...)` from `sum(2 ...)`) doesn't require writing real wiki
    fixture pages."""

    def _scope_coverage(self, *, covered: bool) -> ScopeCoverage:
        return ScopeCoverage(
            scope=SCOPES[0],
            domain="d",
            covered=covered,
            page_count=1 if covered else 0,
            anchor_page="reference/d/x.md" if covered else None,
            suggested_path="reference/d/x.md",
        )

    def test_empty_scopes_is_vacuous_zero_not_one(self):
        # Empty DomainCoverage: 0/0 must read as 0.0 (not covered), the
        # opposite convention from FileCoverage's vacuous 1.0 — a real
        # semantic difference this repo encodes, not an oversight.
        empty = DomainCoverage(domain="d", scopes=[])
        assert domain_coverage_covered_count(empty) == 0
        assert domain_coverage_missing_count(empty) == 0
        assert domain_coverage_coverage_ratio(empty) == 0.0

    def test_partial_coverage_exact_counts_and_ratio(self):
        # 1 covered of 4 scopes: exact counts (not a doubled `sum(2 ...)`
        # mutant) and division, not multiplication (1/4=0.25 vs 1*4=4).
        cov = DomainCoverage(
            domain="d",
            scopes=[
                self._scope_coverage(covered=True),
                self._scope_coverage(covered=False),
                self._scope_coverage(covered=False),
                self._scope_coverage(covered=False),
            ],
        )
        assert domain_coverage_covered_count(cov) == 1
        assert domain_coverage_missing_count(cov) == 3
        assert domain_coverage_coverage_ratio(cov) == 0.25
        assert len(domain_coverage_missing_scopes(cov)) == 3
