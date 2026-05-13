"""Tests for the Phase 4.2 file-doc re-bucket script."""

from __future__ import annotations

import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
sys.path.insert(0, str(_REPO_ROOT))

from wiki_rebucket_file_docs import (  # noqa: E402
    _derive_target_path,
    _extract_file_tag,
    _is_file_doc_path,
    apply,
    plan,
)

from mcp_server.core.wiki_identity import generate_page_id  # noqa: E402
from mcp_server.core.wiki_redirect import parse_frontmatter  # noqa: E402


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _file_doc(
    page_id: str,
    title: str,
    source_path: str,
    tags_extra: tuple[str, ...] = (),
) -> str:
    """Build a representative file-doc page (legacy ``kind: note`` shape)."""
    tags = ["codebase", f"file:{source_path}", "lang:python"]
    tags.extend(tags_extra)
    tag_lines = "\n".join(f"  - {t}" for t in tags)
    return (
        f"---\n"
        f"id: {page_id}\n"
        f"kind: note\n"
        f"created: 2026-05-11T10:43:17Z\n"
        f"updated: 2026-05-11T10:43:17Z\n"
        f"title: {title}\n"
        f"memory_id: 98814\n"
        f"tags:\n{tag_lines}\n"
        f"---\n\n"
        f"# File: {source_path}\n\n"
        f"Stub body — real codebase_analyze content would go here.\n"
    )


# ── Detection helpers ──────────────────────────────────────────────────


def test_is_file_doc_path_matches_canonical_shape() -> None:
    assert (
        _is_file_doc_path("notes/ai-architect-mcp/98814-file-foo.py.md")
        == "ai-architect-mcp"
    )


def test_is_file_doc_path_rejects_unrelated_notes() -> None:
    assert _is_file_doc_path("notes/2026-04-15-changelog-md.md") is None
    assert _is_file_doc_path("adr/_general/2234-foo.md") is None


def test_extract_file_tag_finds_path_from_block_list() -> None:
    fm = {
        "tags": [
            "codebase",
            "file:ai-codebase/hooks/codebase_hook.py",
            "lang:python",
        ]
    }
    assert _extract_file_tag(fm) == "ai-codebase/hooks/codebase_hook.py"


def test_extract_file_tag_missing_returns_empty() -> None:
    assert _extract_file_tag({"tags": ["codebase", "lang:python"]}) == ""
    assert _extract_file_tag({}) == ""


def test_extract_file_tag_handles_inline_list_form() -> None:
    fm = {"tags": "codebase, file:src/main.py, lang:python"}
    assert _extract_file_tag(fm) == "src/main.py"


# ── Slug derivation ────────────────────────────────────────────────────


def test_derive_target_replaces_separators_with_hyphens() -> None:
    target = _derive_target_path("ai-architect-mcp", "hooks/codebase_hook.py")
    assert target == "reference/ai-architect-mcp/hooks-codebase_hook.py.md"


def test_derive_target_empty_source_returns_empty() -> None:
    assert _derive_target_path("foo", "") == ""


def test_derive_target_unknown_domain_falls_back() -> None:
    assert _derive_target_path("", "src/main.py") == "reference/_general/src-main.py.md"


# ── plan() ─────────────────────────────────────────────────────────────


def test_plan_finds_file_doc_notes(tmp_path: Path) -> None:
    pid = generate_page_id()
    _write(
        tmp_path / "notes/cortex/98814-file-src-recall.py.md",
        _file_doc(pid, "File: src/recall.py", "src/recall.py"),
    )
    _write(
        tmp_path / "notes/cortex/2026-04-15-changelog-md.md",
        _file_doc(pid, "Some other note", "src/recall.py"),
    )

    moves = plan(tmp_path)
    # Only the file-* shaped page is matched.
    assert len(moves) == 1
    assert moves[0].rel_path == "notes/cortex/98814-file-src-recall.py.md"
    assert moves[0].target_path == "reference/cortex/src-recall.py.md"
    assert moves[0].page_id == pid


def test_plan_skips_pages_without_id(tmp_path: Path) -> None:
    _write(
        tmp_path / "notes/cortex/98814-file-x.py.md",
        "---\nkind: note\ntitle: X\ntags:\n  - file:x.py\n---\n\nbody\n",
    )
    moves = plan(tmp_path)
    assert len(moves) == 1
    assert moves[0].skip_reason.startswith("missing frontmatter id")


def test_plan_skips_pages_without_file_tag(tmp_path: Path) -> None:
    pid = generate_page_id()
    _write(
        tmp_path / "notes/cortex/98814-file-x.py.md",
        f"---\nid: {pid}\nkind: note\ntitle: No file tag\ntags:\n  - codebase\n---\n\nbody\n",
    )
    moves = plan(tmp_path)
    assert len(moves) == 1
    assert moves[0].skip_reason == "missing ``file:<path>`` tag"


def test_plan_handles_collision_via_disambiguation(tmp_path: Path) -> None:
    """Two notes documenting the same source file get distinct targets.

    Filesystem iteration order is not stable, so we assert on the
    structural property (one bare slug + one disambiguated suffix)
    rather than on which of the two gets which name.
    """
    pid_a = generate_page_id()
    pid_b = generate_page_id()
    _write(
        tmp_path / "notes/cortex/1-file-src-main.py.md",
        _file_doc(pid_a, "File: src/main.py", "src/main.py"),
    )
    _write(
        tmp_path / "notes/cortex/2-file-src-main.py.md",
        _file_doc(pid_b, "File: src/main.py", "src/main.py"),
    )
    moves = plan(tmp_path)
    targets = {m.target_path for m in moves}
    assert len(targets) == 2
    assert "reference/cortex/src-main.py.md" in targets
    # The other one carries a ``-<memory_id>`` suffix (either -1 or -2).
    disambiguated = targets - {"reference/cortex/src-main.py.md"}
    assert len(disambiguated) == 1
    other = next(iter(disambiguated))
    assert other in {
        "reference/cortex/src-main.py-1.md",
        "reference/cortex/src-main.py-2.md",
    }


def test_plan_skips_existing_redirect_stubs(tmp_path: Path) -> None:
    _write(
        tmp_path / "notes/cortex/98814-file-x.py.md",
        "---\nredirect_to: reference/cortex/x.py.md\n---\n\n# Moved\n",
    )
    assert plan(tmp_path) == []


# ── apply() ────────────────────────────────────────────────────────────


def test_apply_writes_modern_frontmatter_at_target(tmp_path: Path) -> None:
    pid = generate_page_id()
    src_path = tmp_path / "notes/cortex/98814-file-src-recall.py.md"
    _write(src_path, _file_doc(pid, "File: src/recall.py", "src/recall.py"))

    moves = plan(tmp_path)
    moved, errors = apply(tmp_path, moves)
    assert moved == 1
    assert errors == []

    target = tmp_path / "reference/cortex/src-recall.py.md"
    assert target.exists()
    fm = parse_frontmatter(target.read_text(encoding="utf-8"))

    # Modern schema applied.
    assert fm["id"] == pid
    assert fm["kind"] == "reference"
    assert fm["lifecycle"] == "seedling"
    assert fm["audience"] == ["developer"]
    assert fm["provenance"] == "auto-generated"
    assert "generator" in fm
    assert fm["source_file_path"] == "src/recall.py"


def test_apply_preserves_body_verbatim(tmp_path: Path) -> None:
    pid = generate_page_id()
    src_path = tmp_path / "notes/cortex/1-file-src-x.py.md"
    page = _file_doc(pid, "File: src/x.py", "src/x.py")
    _write(src_path, page)

    moves = plan(tmp_path)
    apply(tmp_path, moves)

    target_text = (tmp_path / "reference/cortex/src-x.py.md").read_text("utf-8")
    # Body line from the source ends up in the target.
    assert "Stub body — real codebase_analyze content would go here." in target_text


def test_apply_writes_redirect_stub_at_source(tmp_path: Path) -> None:
    pid = generate_page_id()
    src_path = tmp_path / "notes/cortex/1-file-src-x.py.md"
    _write(src_path, _file_doc(pid, "File: src/x.py", "src/x.py"))

    moves = plan(tmp_path)
    apply(tmp_path, moves)

    stub_fm = parse_frontmatter(src_path.read_text("utf-8"))
    assert stub_fm["redirect_to"] == "reference/cortex/src-x.py.md"
    assert stub_fm["redirect_id"] == pid
    assert "Phase 4.2" in str(stub_fm.get("redirect_reason", ""))


def test_apply_refuses_when_destination_exists(tmp_path: Path) -> None:
    pid = generate_page_id()
    src_path = tmp_path / "notes/cortex/1-file-src-x.py.md"
    _write(src_path, _file_doc(pid, "File: src/x.py", "src/x.py"))
    # Pre-existing destination from a prior partial run.
    _write(tmp_path / "reference/cortex/src-x.py.md", "preexisting content")

    moves = plan(tmp_path)
    moved, errors = apply(tmp_path, moves)
    assert moved == 0
    assert any("destination already exists" in e for e in errors)


def test_apply_is_idempotent(tmp_path: Path) -> None:
    """A second --apply pass finds nothing: the source is now a stub
    and is skipped by plan()."""
    pid = generate_page_id()
    src_path = tmp_path / "notes/cortex/1-file-src-x.py.md"
    _write(src_path, _file_doc(pid, "File: src/x.py", "src/x.py"))

    first = plan(tmp_path)
    apply(tmp_path, first)

    second = plan(tmp_path)
    assert second == []


def test_apply_handles_many_pages_across_domains(tmp_path: Path) -> None:
    """Light scalability check — 25 pages across 3 domains."""
    for i in range(10):
        pid = generate_page_id()
        _write(
            tmp_path / f"notes/cortex/{i}-file-src-a-{i}.py.md",
            _file_doc(pid, f"File: src/a/{i}.py", f"src/a/{i}.py"),
        )
    for i in range(10):
        pid = generate_page_id()
        _write(
            tmp_path / f"notes/ai-prd/{i}-file-lib-b-{i}.py.md",
            _file_doc(pid, f"File: lib/b/{i}.py", f"lib/b/{i}.py"),
        )
    for i in range(5):
        pid = generate_page_id()
        _write(
            tmp_path / f"notes/agentic/{i}-file-pkg-c-{i}.py.md",
            _file_doc(pid, f"File: pkg/c/{i}.py", f"pkg/c/{i}.py"),
        )

    moves = plan(tmp_path)
    moved, errors = apply(tmp_path, moves)
    assert moved == 25
    assert errors == []

    # Spot check: a target file in each domain exists and is reference-shaped.
    for domain, file in (
        ("cortex", "src-a-0.py"),
        ("ai-prd", "lib-b-0.py"),
        ("agentic", "pkg-c-0.py"),
    ):
        target = tmp_path / f"reference/{domain}/{file}.md"
        assert target.exists()
        fm = parse_frontmatter(target.read_text("utf-8"))
        assert fm["kind"] == "reference"
        assert fm["provenance"] == "auto-generated"
