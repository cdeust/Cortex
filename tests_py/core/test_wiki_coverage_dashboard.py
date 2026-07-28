"""Tests for core/wiki_coverage_dashboard — the per-project gap report.

The dashboard's contract (module docstring, Meadows Level-6 rationale):
one auto-generated page per project that a reader can scan for (a) slot
coverage in one number, (b) filled vs. queued canonical slots, (c) open
curation-gap count, (d) links into existing anchors. These tests build
real wiki trees under ``tmp_path`` and assert the rendered page /
written files — no mirroring of the line-assembly internals.

``audit_files`` resolves a project source root via ``domain_mapping``;
the session-wide conftest isolation empties the dev-root candidates, so
the no-source-root arm is the natural default here and the with-root
arm is exercised by patching ``audit_files`` with a typed
``FileCoverage``.
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp_server.core import wiki_coverage_dashboard as dash
from mcp_server.core.wiki_coverage import SCOPES, FileCoverage

_SUBSTANTIVE = "x" * 900  # ≥ wiki_coverage._MIN_PAGE_BYTES (800)


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _skeleton_page(gaps: list[str]) -> str:
    gap_block = "\n".join(f"  - {g}" for g in gaps)
    return (
        f"---\ntitle: t\ncuration_gaps:\n{gap_block}\ntags:\n  - file-doc\n---\nbody\n"
    )


# ── _count_curation_gaps_under ────────────────────────────────────────


def test_gap_count_sums_frontmatter_lists_across_pages(tmp_path: Path):
    _write(str(tmp_path / "d" / "a.md"), _skeleton_page(["purpose", "public-api"]))
    _write(str(tmp_path / "d" / "sub" / "b.md"), _skeleton_page(["purpose"]))

    total, gaps = dash._count_curation_gaps_under(tmp_path / "d")

    assert (total, gaps) == (2, 3)


def test_pages_without_frontmatter_count_as_pages_with_zero_gaps(tmp_path: Path):
    _write(str(tmp_path / "d" / "plain.md"), "# no frontmatter here\n")
    _write(str(tmp_path / "d" / "unclosed.md"), "---\ntitle: never closed\n")

    total, gaps = dash._count_curation_gaps_under(tmp_path / "d")

    assert (total, gaps) == (2, 0)


def test_gap_list_ends_at_the_next_unindented_key(tmp_path: Path):
    page = "---\ncuration_gaps:\n  - one\ntags:\n  - not-a-gap\n---\n"
    _write(str(tmp_path / "d" / "a.md"), page)

    _total, gaps = dash._count_curation_gaps_under(tmp_path / "d")

    assert gaps == 1, "tags list entries must not be counted as gaps"


def test_missing_directory_reports_zero(tmp_path: Path):
    assert dash._count_curation_gaps_under(tmp_path / "absent") == (0, 0)


def test_unreadable_page_is_skipped_not_fatal(tmp_path: Path):
    _write(str(tmp_path / "d" / "ok.md"), _skeleton_page(["purpose"]))
    blocked = tmp_path / "d" / "blocked.md"
    _write(str(blocked), _skeleton_page(["purpose"]))
    blocked.chmod(0o000)
    try:
        total, gaps = dash._count_curation_gaps_under(tmp_path / "d")
    finally:
        blocked.chmod(0o644)

    assert total == 2, "the unreadable page still counts as a page"
    assert gaps == 1, "only the readable page's gaps are counted"


# ── _kind_page_counts ─────────────────────────────────────────────────


def test_kind_counts_skip_underscore_and_dot_buckets(tmp_path: Path):
    _write(str(tmp_path / "reference" / "p" / "a.md"), "x")
    _write(str(tmp_path / "reference" / "p" / "deep" / "b.md"), "x")
    _write(str(tmp_path / "adr" / "p" / "c.md"), "x")
    _write(str(tmp_path / "_dashboards" / "p" / "d.md"), "x")
    _write(str(tmp_path / "adr" / "other-domain" / "e.md"), "x")
    _write(str(tmp_path / "runbook" / "other-domain" / "f.md"), "x")

    counts = dash._kind_page_counts(tmp_path, "p")

    assert counts == {"reference": 2, "adr": 1}
    assert "runbook" not in counts, "kind without this domain is omitted"


# ── render_dashboard ──────────────────────────────────────────────────


def test_fresh_domain_renders_all_slots_as_queued(tmp_path: Path):
    page = dash.render_dashboard(str(tmp_path), "fresh")

    assert page.startswith("---\n")
    assert "title: fresh — documentation coverage" in page
    assert "provenance: auto-generated" in page
    assert f"* **Canonical slots filled:** 0/{len(SCOPES)} (0%)" in page
    assert page.count("✗ **missing — queued**") == len(SCOPES)
    assert "## What's still missing — and what should be in each" in page
    assert (
        "* **Source files referenced somewhere:** _(no source root resolved)_" in page
    ), "conftest empties the dev roots, so no source root resolves"


def test_filled_slot_links_its_anchor_and_leaves_the_missing_section(
    tmp_path: Path,
):
    _write(str(tmp_path / "reference" / "p" / "architecture-overview.md"), _SUBSTANTIVE)

    page = dash.render_dashboard(str(tmp_path), "p")

    assert "✅ filled" in page
    assert "[`reference/p/architecture-overview.md`]" in page
    assert f"* **Canonical slots filled:** 1/{len(SCOPES)}" in page
    assert "## Pages by kind" in page
    assert "| reference | 1 |" in page


def test_open_gaps_are_totalled_on_the_scoreboard(tmp_path: Path):
    _write(
        str(tmp_path / "reference" / "p" / "mod.md"),
        _skeleton_page(["purpose", "invariants"]),
    )

    page = dash.render_dashboard(str(tmp_path), "p")

    assert "* **Total wiki pages for this project:** 1" in page
    assert "* **Open curation gaps awaiting LLM authoring:** 2" in page


def test_resolved_source_root_reports_file_coverage_and_caps_the_list(
    tmp_path: Path, monkeypatch
):
    uncovered = [f"src/file{i}.py" for i in range(35)]
    monkeypatch.setattr(
        dash,
        "audit_files",
        lambda root, domain: FileCoverage(
            domain=domain,
            source_root="/repo",
            source_file_count=40,
            covered_file_count=5,
            uncovered_files=uncovered,
        ),
    )

    page = dash.render_dashboard(str(tmp_path), "p")

    assert "* **Source files referenced somewhere:** 5/40 (12%)" in page
    assert "## Source files not yet referenced anywhere" in page
    assert "src/file29.py" in page
    assert "src/file30.py" not in page, "listing is capped at 30 entries"
    assert "… +5 more" in page


# ── write_dashboards ──────────────────────────────────────────────────


def test_write_dashboards_emits_one_page_per_domain_plus_index(tmp_path: Path):
    written = dash.write_dashboards(tmp_path, domains=["alpha", "beta"])

    assert set(written) == {"alpha", "beta"}
    for domain, path in written.items():
        text = Path(path).read_text(encoding="utf-8")
        assert f"# {domain} — documentation coverage" in text
    index = (tmp_path / "_dashboards" / "_index.md").read_text(encoding="utf-8")
    assert "| alpha | [`_dashboards/alpha.md`](_dashboards/alpha.md) |" in index
    assert "| beta | [`_dashboards/beta.md`](_dashboards/beta.md) |" in index


def test_write_dashboards_on_missing_root_writes_nothing(tmp_path: Path):
    assert dash.write_dashboards(tmp_path / "absent") == {}


def test_write_dashboards_registry_failure_writes_nothing(tmp_path: Path, monkeypatch):
    def _boom():
        raise RuntimeError("registry unavailable")

    # Patch the consumer's binding (top-level import, #197 family 4).
    monkeypatch.setattr(dash, "_build_registry", _boom)

    assert dash.write_dashboards(tmp_path) == {}
    assert not (tmp_path / "_dashboards").exists(), "no partial output"


def test_unwritable_dashboard_is_skipped_and_the_batch_continues(tmp_path: Path):
    # Pre-create `alpha.md` as a DIRECTORY so write_text raises OSError.
    (tmp_path / "_dashboards" / "alpha.md").mkdir(parents=True)

    written = dash.write_dashboards(tmp_path, domains=["alpha", "beta"])

    assert set(written) == {"beta"}, "the failed domain is dropped, not fatal"
    index = (tmp_path / "_dashboards" / "_index.md").read_text(encoding="utf-8")
    assert "alpha" not in index, "the index lists only what was written"


def test_unwritable_index_does_not_lose_the_dashboards(tmp_path: Path):
    (tmp_path / "_dashboards" / "_index.md").mkdir(parents=True)

    written = dash.write_dashboards(tmp_path, domains=["alpha"])

    assert set(written) == {"alpha"}, "index write failure is best-effort"


def test_write_dashboards_default_domains_come_from_the_registry(
    tmp_path: Path, monkeypatch
):
    # The registry is isolated to zero repos by conftest; patch the
    # discovery seam the module actually calls to prove the default
    # path flows registry domains into pages.
    from mcp_server.shared.domain_mapping import RepoInfo

    class _Registry:
        # A real RepoInfo whose fs_path does not exist: audit_files
        # resolves the root, finds no source files, and degrades cleanly.
        repos = [
            RepoInfo(
                fs_path=str(tmp_path / "no-such-checkout"),
                dir_name="gamma",
                remote_name="gamma",
                canonical="gamma",
            )
        ]

    # Patch the consumer's binding (top-level import, #197 family 4).
    monkeypatch.setattr(dash, "_build_registry", lambda: _Registry())

    written = dash.write_dashboards(tmp_path)

    assert set(written) == {"gamma"}
