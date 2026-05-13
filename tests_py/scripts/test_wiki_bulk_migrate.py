"""Tests for the Phase 4 bulk-migration script."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
sys.path.insert(0, str(_REPO_ROOT))

from wiki_bulk_migrate import (  # noqa: E402
    _apply_plan,
    _clean_title_candidate,
    _detect_double_md,
    _detect_path_leak_slug,
    _detect_timestamp_slug,
    _derive_clean_slug,
    plan,
)

from mcp_server.core.wiki_identity import generate_page_id  # noqa: E402
from mcp_server.core.wiki_redirect import parse_frontmatter  # noqa: E402


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _page(page_id: str, title: str, body: str = "Body.") -> str:
    return f"---\nid: {page_id}\ntitle: {title}\n---\n\n# {title}\n\n{body}\n"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── Detection ───────────────────────────────────────────────────────────


def test_detect_double_md_strips_duplicate_suffix() -> None:
    is_double, target = _detect_double_md("adr/_general/2234-zero-dependencies.md.md")
    assert is_double
    assert target == "adr/_general/2234-zero-dependencies.md"


def test_detect_double_md_rejects_single_extension() -> None:
    assert _detect_double_md("adr/foo.md") == (False, "")


def test_detect_timestamp_slug_full_shape() -> None:
    assert _detect_timestamp_slug(
        "adr/_general/1828-decision-created-2026-04-15t09-29-10z.md"
    )


def test_detect_timestamp_slug_negative() -> None:
    assert not _detect_timestamp_slug("adr/_general/2234-zero-dependencies.md")
    assert not _detect_timestamp_slug("notes/2026-04-15-changelog.md")


def test_detect_path_leak_slug() -> None:
    assert _detect_path_leak_slug(
        "specs/2026/2026-04-17-also-on-users-cdeust-documents-developments-ai.md"
    )
    assert _detect_path_leak_slug(
        "notes/2026/2026-04-17-why-was-ls-users-cdeust-documents-developments-x.md"
    )


def test_detect_path_leak_slug_negative() -> None:
    assert not _detect_path_leak_slug("notes/2026-04-15-changelog.md")
    assert not _detect_path_leak_slug("adr/_general/2234-zero-dependencies.md")


# ── Slug derivation ────────────────────────────────────────────────────


def test_clean_title_accepts_real_titles() -> None:
    assert _clean_title_candidate("Use pgvector for retrieval")
    assert _clean_title_candidate("Zero external dependencies")


def test_clean_title_rejects_path_shapes() -> None:
    assert not _clean_title_candidate("/Users/cdeust/Documents/Developments/x")


def test_clean_title_rejects_timestamp_shapes() -> None:
    assert not _clean_title_candidate("2026-04-15T09:29:10Z")


def test_clean_title_rejects_too_short() -> None:
    assert not _clean_title_candidate("ok")


def test_derive_clean_slug_uses_frontmatter_title() -> None:
    text = "---\ntitle: Use pgvector for retrieval\n---\n\n# heading\n"
    fm = {"title": "Use pgvector for retrieval"}
    assert _derive_clean_slug(text, fm, "fallback") == "use-pgvector-for-retrieval"


def test_derive_clean_slug_falls_back_to_body_heading() -> None:
    text = "---\ntitle: \n---\n\n## Zero external dependencies\n\nBody."
    fm = {"title": ""}
    slug = _derive_clean_slug(text, fm, "fallback")
    assert slug == "zero-external-dependencies"


def test_derive_clean_slug_falls_back_to_hash() -> None:
    text = "---\ntitle: /Users/cdeust/x\n---\n\nbody"
    fm = {"title": "/Users/cdeust/x"}
    slug = _derive_clean_slug(text, fm, "page")
    assert slug.startswith("page-")
    assert len(slug) > len("page-")


# ── plan() ──────────────────────────────────────────────────────────────


def test_plan_finds_all_three_pollution_classes(tmp_path: Path) -> None:
    pid_a = generate_page_id()
    pid_b = generate_page_id()
    pid_c = generate_page_id()
    pid_clean = generate_page_id()

    _write(
        tmp_path / "adr/_general/2234-zero-dependencies.md.md",
        _page(pid_a, "Zero dependencies decision"),
    )
    _write(
        tmp_path / "adr/_general/1828-decision-created-2026-04-15t09-29-10z.md",
        _page(pid_b, "Adopt pgvector"),
    )
    _write(
        tmp_path
        / "specs/2026/2026-04-17-also-on-users-cdeust-documents-developments-x.md",
        _page(pid_c, "Spec — pgvector adoption"),
    )
    _write(
        tmp_path / "adr/_general/2300-clean.md",
        _page(pid_clean, "A clean ADR"),
    )

    items = plan(tmp_path)
    by_pattern = {p.pattern for p in items}
    assert by_pattern == {"double-md", "timestamp-slug", "path-leak"}
    assert len(items) == 3


def test_plan_skips_pages_without_id(tmp_path: Path) -> None:
    _write(
        tmp_path / "adr/_general/2234-zero-dependencies.md.md",
        "---\ntitle: No id\n---\n\nbody\n",
    )
    items = plan(tmp_path)
    assert len(items) == 1
    assert items[0].skipped_reason.startswith("missing frontmatter id")


def test_plan_skips_redirect_stubs(tmp_path: Path) -> None:
    _write(
        tmp_path / "adr/_general/2234-zero-dependencies.md.md",
        "---\nredirect_to: adr/_general/2234-zero-dependencies.md\n---\n\n# Moved\n",
    )
    assert plan(tmp_path) == []


def test_plan_proposes_clean_target_for_timestamp_adr(tmp_path: Path) -> None:
    pid = generate_page_id()
    _write(
        tmp_path / "adr/_general/1828-decision-created-2026-04-15t09-29-10z.md",
        _page(pid, "Adopt pgvector for ANN"),
    )
    items = plan(tmp_path)
    assert len(items) == 1
    item = items[0]
    assert item.pattern == "timestamp-slug"
    # Preserves the numeric prefix and uses the frontmatter title.
    assert item.proposed_path == "adr/_general/1828-adopt-pgvector-for-ann.md"


def test_plan_proposes_clean_target_for_path_leak(tmp_path: Path) -> None:
    pid = generate_page_id()
    _write(
        tmp_path
        / "specs/2026/2026-04-17-also-on-users-cdeust-documents-developments-x.md",
        _page(pid, "Spec for pgvector adoption"),
    )
    items = plan(tmp_path)
    assert len(items) == 1
    # Preserves the YYYY-MM-DD- date prefix observed in the wiki.
    assert items[0].proposed_path == (
        "specs/2026/2026-04-17-spec-for-pgvector-adoption.md"
    )


# ── Apply (end-to-end with wiki_rename) ────────────────────────────────


def test_apply_renames_and_creates_stubs(tmp_path: Path) -> None:
    pid = generate_page_id()
    src = tmp_path / "adr/_general/2234-zero-dependencies.md.md"
    _write(src, _page(pid, "Zero dependencies"))

    items = plan(tmp_path)
    assert len(items) == 1

    renamed, errors = _run(_apply_plan(items, tmp_path))
    assert renamed == 1
    assert errors == []

    # New path holds the content with the original id.
    new = tmp_path / "adr/_general/2234-zero-dependencies.md"
    assert new.exists()
    new_fm = parse_frontmatter(new.read_text("utf-8"))
    assert new_fm["id"] == pid

    # Old path is now a redirect stub.
    stub_fm = parse_frontmatter(src.read_text("utf-8"))
    assert stub_fm["redirect_to"] == "adr/_general/2234-zero-dependencies.md"
    assert stub_fm["redirect_id"] == pid


def test_apply_is_idempotent(tmp_path: Path) -> None:
    """A second --apply run finds zero pollution paths (the renames
    landed; their stubs are detected and skipped)."""
    pid = generate_page_id()
    _write(
        tmp_path / "adr/_general/2234-foo.md.md",
        _page(pid, "Foo"),
    )

    first_items = plan(tmp_path)
    _run(_apply_plan(first_items, tmp_path))

    # Second plan finds nothing (the .md.md was renamed; the stub at
    # the .md.md path is detected and skipped).
    second_items = plan(tmp_path)
    assert second_items == []


def test_apply_handles_three_classes_in_one_pass(tmp_path: Path) -> None:
    p1 = generate_page_id()
    p2 = generate_page_id()
    p3 = generate_page_id()
    _write(
        tmp_path / "adr/_general/2234-zero-dependencies.md.md",
        _page(p1, "Zero dependencies"),
    )
    _write(
        tmp_path / "adr/_general/1828-decision-created-2026-04-15t09-29-10z.md",
        _page(p2, "Adopt pgvector"),
    )
    _write(
        tmp_path
        / "specs/2026/2026-04-17-also-on-users-cdeust-documents-developments-x.md",
        _page(p3, "Spec page"),
    )

    items = plan(tmp_path)
    renamed, errors = _run(_apply_plan(items, tmp_path))
    assert renamed == 3
    assert errors == []
    # Every original path now holds a stub; every proposed path holds content.
    for item in items:
        src_fm = parse_frontmatter((tmp_path / item.rel_path).read_text("utf-8"))
        assert "redirect_to" in src_fm
        assert (tmp_path / item.proposed_path).exists()


def test_apply_skips_id_less_pages_without_erroring(tmp_path: Path) -> None:
    """When a polluted page lacks an id we skip it (plan() records the
    skip reason) — apply must not crash on such items."""
    _write(
        tmp_path / "adr/_general/2234-foo.md.md",
        "---\ntitle: No id\n---\n\nbody\n",
    )
    items = plan(tmp_path)
    renamed, errors = _run(_apply_plan(items, tmp_path))
    assert renamed == 0
    assert errors == []
