"""Tests for the wiki page-ID backfill script (Phase 3 of ADR-2244)."""

from __future__ import annotations

import sys
from pathlib import Path

# The backfill script lives under scripts/ rather than the package. Add
# scripts/ to sys.path so we can import it as a module.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
sys.path.insert(0, str(_REPO_ROOT))

from wiki_backfill_ids import run  # noqa: E402

from mcp_server.core.wiki_identity import extract_page_id, is_valid_page_id  # noqa: E402
from mcp_server.core.wiki_redirect import parse_frontmatter  # noqa: E402


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ── Dry-run (default) ─────────────────────────────────────────────────


def test_dry_run_does_not_write_to_disk(tmp_path: Path) -> None:
    page = tmp_path / "notes" / "no-id.md"
    original = "---\ntitle: A page\nupdated: 2026-05-13\n---\n\nBody.\n"
    _write(page, original)

    summary = run(tmp_path, apply=False)
    assert summary.minted == 1
    assert page.read_text(encoding="utf-8") == original  # unchanged


def test_dry_run_counts_what_would_be_minted(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "---\ntitle: A\n---\n\nbody\n")
    _write(tmp_path / "b.md", "---\ntitle: B\n---\n\nbody\n")
    _write(
        tmp_path / "c.md",
        "---\ntitle: C\nid: adfb8a1f-1b58-4f0c-9a7e-4c5e6c8d9f12\n---\n\nbody\n",
    )
    summary = run(tmp_path, apply=False)
    assert summary.scanned == 3
    assert summary.minted == 2
    assert summary.already_has_id == 1


# ── Apply ─────────────────────────────────────────────────────────────


def test_apply_writes_valid_id_to_frontmatter(tmp_path: Path) -> None:
    page = tmp_path / "adr" / "0001-foo.md"
    _write(page, "---\ntitle: Foo\nstatus: accepted\n---\n\n## Decision\n\nFoo.\n")

    run(tmp_path, apply=True)

    new_text = page.read_text(encoding="utf-8")
    fm = parse_frontmatter(new_text)
    page_id = extract_page_id(fm)
    assert page_id is not None
    assert is_valid_page_id(page_id)
    # Original frontmatter keys preserved.
    assert fm["title"] == "Foo"
    assert fm["status"] == "accepted"
    # Body preserved verbatim.
    assert "## Decision" in new_text
    assert "Foo." in new_text


def test_apply_is_idempotent(tmp_path: Path) -> None:
    """Running --apply twice mints exactly once. Second run finds nothing to do."""
    page = tmp_path / "notes" / "x.md"
    _write(page, "---\ntitle: X\n---\n\nbody\n")

    first = run(tmp_path, apply=True)
    second = run(tmp_path, apply=True)

    assert first.minted == 1
    assert second.minted == 0
    assert second.already_has_id == 1


def test_each_page_gets_distinct_id(tmp_path: Path) -> None:
    for i in range(5):
        _write(tmp_path / f"page-{i}.md", f"---\ntitle: P{i}\n---\n\nbody\n")
    run(tmp_path, apply=True)
    ids: set[str] = set()
    for i in range(5):
        fm = parse_frontmatter((tmp_path / f"page-{i}.md").read_text("utf-8"))
        pid = extract_page_id(fm)
        assert pid is not None
        ids.add(pid)
    assert len(ids) == 5


# ── Skipped categories ────────────────────────────────────────────────


def test_redirect_stubs_are_skipped(tmp_path: Path) -> None:
    """Stubs reference another page's id; they don't get their own."""
    page = tmp_path / "old-path.md"
    _write(
        page,
        "---\nredirect_to: new-path.md\nredirect_reason: rename\n---\n\n"
        "# Moved\n\nThis page has moved.\n",
    )
    summary = run(tmp_path, apply=True)
    assert summary.skipped_redirects == 1
    assert summary.minted == 0
    # No id added to the stub.
    assert "id:" not in page.read_text("utf-8").split("---", 2)[1]


def test_pages_without_frontmatter_are_skipped(tmp_path: Path) -> None:
    """Body-only pages (no frontmatter) aren't valid wiki pages — skip rather
    than synthesise a frontmatter block."""
    page = tmp_path / "raw.md"
    _write(page, "# Just a heading\n\nNo frontmatter.\n")
    summary = run(tmp_path, apply=True)
    assert summary.skipped_no_frontmatter == 1
    assert summary.minted == 0
    # Body unchanged.
    assert page.read_text("utf-8") == "# Just a heading\n\nNo frontmatter.\n"


def test_generated_dir_is_ignored(tmp_path: Path) -> None:
    """``.generated/INDEX.md`` and any other dotted top-level dirs are
    ignored — they're auto-rebuilt, not authored content."""
    _write(tmp_path / ".generated" / "INDEX.md", "---\ntitle: index\n---\n")
    _write(tmp_path / "authored.md", "---\ntitle: A\n---\n")
    summary = run(tmp_path, apply=True)
    assert summary.scanned == 1
    assert summary.minted == 1


# ── Malformed inputs ──────────────────────────────────────────────────


def test_existing_malformed_id_is_treated_as_missing(tmp_path: Path) -> None:
    page = tmp_path / "bad-id.md"
    _write(page, "---\nid: garbage\ntitle: Bad\n---\n\nbody\n")

    summary = run(tmp_path, apply=True)
    assert summary.minted == 1

    fm = parse_frontmatter(page.read_text("utf-8"))
    new_id = extract_page_id(fm)
    assert new_id is not None
    assert is_valid_page_id(new_id)
    assert new_id != "garbage"
