"""Direct (non-mocked) coverage for candidate_scan's filesystem scan.

Every other test in this package monkeypatches ``_scan_pages_with_gaps``
out entirely (see test_headless_authoring_throttle.py /
test_import_cycle_237.py), so the real walking/filtering/tuple-building
logic in ``_gap_entry_for_page`` had zero test-suite coverage before
this file — a gap mutation testing surfaced during issue #276's Extract
Function pass over candidate_scan.py (mutmut showed survivors on the
dotfile-prefix check and the appended-tuple content, both invisible to
the mocked-out test suite). These tests exercise the real filesystem
walk against a tmp_path wiki tree.
"""

from __future__ import annotations

from pathlib import Path

from mcp_server.handlers.consolidation.candidate_scan import _scan_pages_with_gaps


def _write_page(
    path: Path, *, gaps: list[str] | None = None, extra_frontmatter: str = ""
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    gaps_block = ""
    if gaps:
        gaps_block = "curation_gaps:\n" + "".join(f"  - {g}\n" for g in gaps)
    path.write_text(
        f"---\ntitle: test page\n{extra_frontmatter}{gaps_block}---\nBody text.\n",
        encoding="utf-8",
    )


def test_scan_pages_with_gaps_finds_frozen_gap_pages(tmp_path: Path) -> None:
    """A page with a non-empty curation_gaps list is returned verbatim."""
    page = tmp_path / "architecture.md"
    _write_page(page, gaps=["callers", "consumers"])

    result = _scan_pages_with_gaps(tmp_path)

    assert len(result) == 1
    found_path, meta, body = result[0]
    assert found_path == page
    assert meta["curation_gaps"] == ["callers", "consumers"]
    assert body.strip() == "Body text."


def test_scan_pages_with_gaps_skips_page_without_gaps(tmp_path: Path) -> None:
    """A page with no curation_gaps and not kind=reference is excluded."""
    _write_page(tmp_path / "complete.md", gaps=None)

    assert _scan_pages_with_gaps(tmp_path) == []


def test_scan_pages_with_gaps_skips_dotfile_and_underscore_dirs(tmp_path: Path) -> None:
    """Pages under a dot- or underscore-prefixed directory are never scanned,
    even when they carry curation_gaps (e.g. ``_drafts/`` or ``.trash/``).
    """
    _write_page(tmp_path / "_drafts" / "wip.md", gaps=["callers"])
    _write_page(tmp_path / ".trash" / "old.md", gaps=["callers"])

    assert _scan_pages_with_gaps(tmp_path) == []


def test_scan_pages_with_gaps_returns_empty_for_missing_dir(tmp_path: Path) -> None:
    """A non-existent wiki_root returns [] rather than raising."""
    assert _scan_pages_with_gaps(tmp_path / "does-not-exist") == []


def test_scan_pages_with_gaps_multiple_pages_mixed(tmp_path: Path) -> None:
    """Only the gap-carrying page is returned when siblings have none."""
    gapped = tmp_path / "with-gaps.md"
    _write_page(gapped, gaps=["parameters"])
    _write_page(tmp_path / "without-gaps.md", gaps=None)

    result = _scan_pages_with_gaps(tmp_path)

    assert [p for p, _, _ in result] == [gapped]


def test_scan_pages_with_gaps_live_audits_file_docs_with_no_frozen_gaps(
    tmp_path: Path,
) -> None:
    """A kind=reference file-doc with a source_file_path but no frozen
    curation_gaps is still included when the live section audit (added
    after the page was generated) finds missing canonical sections.
    """
    page = tmp_path / "reference.md"
    _write_page(
        page,
        gaps=None,
        extra_frontmatter="kind: reference\nsource_file_path: src/foo.py\n",
    )

    result = _scan_pages_with_gaps(tmp_path)

    assert [p for p, _, _ in result] == [page]


def test_scan_pages_with_gaps_skips_non_reference_kind_even_with_source_path(
    tmp_path: Path,
) -> None:
    """The live-audit axis only force-audits kind=reference file-docs —
    an ADR/spec/guide with a source_file_path is never live-audited.
    """
    _write_page(
        tmp_path / "adr.md",
        gaps=None,
        extra_frontmatter="kind: adr\nsource_file_path: src/foo.py\n",
    )

    assert _scan_pages_with_gaps(tmp_path) == []
