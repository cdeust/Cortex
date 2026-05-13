"""Handler-layer tests for redirect mechanics (ADR-2244 Phase 3.2).

Exercises wiki_read (transparent follow), wiki_list / wiki_reindex
(stub filtering), and wiki_rename (atomic move + stub creation) against
a temporary wiki root.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from mcp_server.core.wiki_identity import (
    extract_page_id,
    generate_page_id,
    is_valid_page_id,
)
from mcp_server.core.wiki_redirect import parse_frontmatter
from mcp_server.handlers import wiki_list, wiki_read, wiki_reindex, wiki_rename


# ── Test infrastructure ──────────────────────────────────────────────


@pytest.fixture
def tmp_wiki(tmp_path: Path, monkeypatch):
    """Point WIKI_ROOT at a temp directory for the duration of the test.

    The handlers import ``WIKI_ROOT`` at module load. The wiki_store
    helpers each take a ``root`` argument, so the simplest reliable
    intercept is to monkeypatch the symbol in every handler that
    imports it.
    """
    # The handlers import ``from mcp_server.infrastructure.config import WIKI_ROOT``.
    # Each handler now holds its own binding, so we patch each one.
    for mod in (wiki_read, wiki_list, wiki_reindex, wiki_rename):
        monkeypatch.setattr(mod, "WIKI_ROOT", str(tmp_path))
    return tmp_path


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _page(page_id: str, title: str, body: str = "Body.") -> str:
    return (
        f"---\nid: {page_id}\ntitle: {title}\nkind: explanation\n"
        f"lifecycle: seedling\naudience:\n  - developer\n"
        f"provenance: human\n---\n\n# {title}\n\n{body}\n"
    )


def _stub(target_path: str, target_id: str | None = None, reason: str = "") -> str:
    lines = ["---", f"redirect_to: {target_path}"]
    if target_id:
        lines.append(f"redirect_id: {target_id}")
    if reason:
        lines.append(f"redirect_reason: {reason}")
    lines.append("---")
    lines.append("")
    lines.append("# Moved\n")
    return "\n".join(lines)


# ── wiki_read: redirect resolution ───────────────────────────────────


def test_read_returns_content_for_normal_page(tmp_wiki: Path) -> None:
    pid = generate_page_id()
    _write(tmp_wiki / "adr/0001-foo.md", _page(pid, "Foo"))

    result = _run(wiki_read.handler({"path": "adr/0001-foo.md"}))
    assert "content" in result
    assert "title: Foo" in result["content"]
    assert result["path"] == "adr/0001-foo.md"
    assert result["redirect_chain"] == []


def test_read_follows_single_hop_redirect(tmp_wiki: Path) -> None:
    pid = generate_page_id()
    _write(tmp_wiki / "new.md", _page(pid, "New home"))
    _write(tmp_wiki / "old.md", _stub("new.md", target_id=pid))

    result = _run(wiki_read.handler({"path": "old.md"}))
    assert "error" not in result
    assert result["path"] == "new.md"
    assert "title: New home" in result["content"]
    assert result["redirect_chain"] == ["old.md", "new.md"]


def test_read_follows_multi_hop_chain(tmp_wiki: Path) -> None:
    pid = generate_page_id()
    _write(tmp_wiki / "v3.md", _page(pid, "Final"))
    _write(tmp_wiki / "v2.md", _stub("v3.md"))
    _write(tmp_wiki / "v1.md", _stub("v2.md"))

    result = _run(wiki_read.handler({"path": "v1.md"}))
    assert result["path"] == "v3.md"
    assert "title: Final" in result["content"]
    assert result["redirect_chain"] == ["v1.md", "v2.md", "v3.md"]


def test_read_follow_false_returns_stub_itself(tmp_wiki: Path) -> None:
    pid = generate_page_id()
    _write(tmp_wiki / "new.md", _page(pid, "New"))
    _write(tmp_wiki / "old.md", _stub("new.md", target_id=pid))

    result = _run(wiki_read.handler({"path": "old.md", "follow_redirects": False}))
    assert result["path"] == "old.md"
    assert "redirect_to: new.md" in result["content"]
    assert result["redirect_chain"] == []


def test_read_cycle_returns_error(tmp_wiki: Path) -> None:
    _write(tmp_wiki / "a.md", _stub("b.md"))
    _write(tmp_wiki / "b.md", _stub("a.md"))

    result = _run(wiki_read.handler({"path": "a.md"}))
    assert "error" in result
    assert "could not be resolved" in result["error"]


def test_read_dangling_redirect_returns_error(tmp_wiki: Path) -> None:
    """Stub points at a path that doesn't exist on disk."""
    _write(tmp_wiki / "old.md", _stub("nope/missing.md"))

    result = _run(wiki_read.handler({"path": "old.md"}))
    # ``resolve_chain`` reads frontmatter and gets {} for missing path,
    # which parse_redirect treats as "not a redirect" → resolve terminates
    # at nope/missing.md, but read_page returns None for missing → error.
    assert "error" in result


def test_read_missing_source_returns_error(tmp_wiki: Path) -> None:
    result = _run(wiki_read.handler({"path": "does-not-exist.md"}))
    assert "error" in result
    assert "not found" in result["error"]


# ── wiki_list: redirect filtering ────────────────────────────────────


def test_list_excludes_redirect_stubs_by_default(tmp_wiki: Path) -> None:
    pid = generate_page_id()
    _write(tmp_wiki / "adr/live.md", _page(pid, "Live page"))
    _write(tmp_wiki / "adr/old.md", _stub("adr/live.md", target_id=pid))

    result = _run(wiki_list.handler({"kind": "adr"}))
    assert "adr/live.md" in result["pages"]
    assert "adr/old.md" not in result["pages"]
    assert result["count"] == 1
    assert result["redirect_count"] == 1


def test_list_include_redirects_returns_all(tmp_wiki: Path) -> None:
    pid = generate_page_id()
    _write(tmp_wiki / "adr/live.md", _page(pid, "Live"))
    _write(tmp_wiki / "adr/old.md", _stub("adr/live.md"))

    result = _run(wiki_list.handler({"kind": "adr", "include_redirects": True}))
    assert "adr/live.md" in result["pages"]
    assert "adr/old.md" in result["pages"]
    assert result["count"] == 2


def test_list_no_redirects_means_redirect_count_zero(tmp_wiki: Path) -> None:
    pid = generate_page_id()
    _write(tmp_wiki / "adr/a.md", _page(pid, "A"))

    result = _run(wiki_list.handler({"kind": "adr"}))
    assert result["redirect_count"] == 0


# ── Phase 5: auto-generated filter ────────────────────────────────────


def _auto_gen_page(page_id: str, title: str) -> str:
    """A page whose frontmatter declares ``provenance: auto-generated``."""
    return (
        f"---\nid: {page_id}\ntitle: {title}\nkind: reference\n"
        f"lifecycle: seedling\naudience:\n  - developer\n"
        f"provenance: auto-generated\ngenerator:\n"
        f"  model: cortex-codebase-analyze\n  version: v1\n"
        f"---\n\n# {title}\n\nAuto-gen body.\n"
    )


def test_list_excludes_auto_generated_by_default(tmp_wiki: Path) -> None:
    """Phase 5 of ADR-2244: ``provenance: auto-generated`` pages are
    hidden from the default listing — at ~8,700 pages they would
    dominate any view."""
    pid_human = generate_page_id()
    pid_auto = generate_page_id()
    _write(tmp_wiki / "reference/cortex/curated.md", _page(pid_human, "Curated"))
    _write(
        tmp_wiki / "reference/cortex/file-x.py.md",
        _auto_gen_page(pid_auto, "File: x.py"),
    )

    result = _run(wiki_list.handler({"kind": "reference"}))
    assert "reference/cortex/curated.md" in result["pages"]
    assert "reference/cortex/file-x.py.md" not in result["pages"]
    assert result["count"] == 1
    assert result["auto_generated_count"] == 1


def test_list_include_auto_generated_returns_both(tmp_wiki: Path) -> None:
    pid_human = generate_page_id()
    pid_auto = generate_page_id()
    _write(tmp_wiki / "reference/cortex/curated.md", _page(pid_human, "Curated"))
    _write(
        tmp_wiki / "reference/cortex/file-x.py.md",
        _auto_gen_page(pid_auto, "File: x.py"),
    )

    result = _run(
        wiki_list.handler({"kind": "reference", "include_auto_generated": True})
    )
    assert "reference/cortex/curated.md" in result["pages"]
    assert "reference/cortex/file-x.py.md" in result["pages"]
    assert result["count"] == 2


def test_list_both_filters_compose_correctly(tmp_wiki: Path) -> None:
    """Redirect stub of an auto-gen page: counted as redirect, hidden
    by default. Verifies the two filters don't double-count or fight
    each other."""
    pid = generate_page_id()
    _write(
        tmp_wiki / "reference/cortex/curated.md",
        _page(generate_page_id(), "Curated"),
    )
    _write(
        tmp_wiki / "reference/cortex/file-x.py.md",
        _auto_gen_page(pid, "File: x.py"),
    )
    _write(
        tmp_wiki / "reference/cortex/old-file-path.md",
        _stub("reference/cortex/file-x.py.md", target_id=pid),
    )

    result = _run(wiki_list.handler({"kind": "reference"}))
    # Only the curated human-authored page is visible.
    assert result["count"] == 1
    assert "reference/cortex/curated.md" in result["pages"]
    assert result["redirect_count"] == 1
    assert result["auto_generated_count"] == 1


def test_list_fast_path_when_both_filters_disabled(tmp_wiki: Path) -> None:
    """When both filters are off, the handler avoids the per-page
    frontmatter read and returns the raw list."""
    _write(tmp_wiki / "adr/a.md", _page(generate_page_id(), "A"))
    _write(
        tmp_wiki / "adr/b.md",
        _auto_gen_page(generate_page_id(), "B"),
    )
    result = _run(
        wiki_list.handler(
            {
                "kind": "adr",
                "include_redirects": True,
                "include_auto_generated": True,
            }
        )
    )
    assert result["count"] == 2
    assert result["redirect_count"] == 0  # not partitioned in fast path
    assert result["auto_generated_count"] == 0


# ── Phase 5: reindex separates auto-gen into its own section ─────────


def test_reindex_separates_auto_generated_from_human_authored(
    tmp_wiki: Path,
) -> None:
    """INDEX.md must surface human-authored content first; auto-gen
    reference pages get their own clearly-marked tail section."""
    _write(
        tmp_wiki / "reference/cortex/curated.md",
        _page(generate_page_id(), "Curated"),
    )
    _write(
        tmp_wiki / "reference/cortex/file-x.py.md",
        _auto_gen_page(generate_page_id(), "File: x.py"),
    )
    _write(
        tmp_wiki / "reference/cortex/file-y.py.md",
        _auto_gen_page(generate_page_id(), "File: y.py"),
    )

    result = _run(wiki_reindex.handler({}))
    assert result["by_kind"]["reference"] == 1
    assert result["auto_generated_count"] == 2
    assert result["auto_generated_by_kind"]["reference"] == 2

    index = (tmp_wiki / ".generated" / "INDEX.md").read_text("utf-8")
    # Both sections exist, in the right order.
    h_pos = index.find("## Human-authored")
    a_pos = index.find("## Auto-generated reference")
    assert h_pos >= 0
    assert a_pos >= 0
    assert h_pos < a_pos
    # Curated page in human-authored section, auto-gen pages below.
    assert "curated.md" in index
    assert "file-x.py.md" in index
    assert "file-y.py.md" in index


# ── wiki_reindex: stubs not in INDEX.md ──────────────────────────────


def test_reindex_excludes_redirects_from_index(tmp_wiki: Path) -> None:
    pid = generate_page_id()
    _write(tmp_wiki / "adr/live.md", _page(pid, "Live"))
    _write(tmp_wiki / "adr/old.md", _stub("adr/live.md"))

    result = _run(wiki_reindex.handler({}))
    assert result["redirect_count"] == 1
    assert result["by_kind"]["adr"] == 1  # only the live page counted

    index = (tmp_wiki / ".generated" / "INDEX.md").read_text(encoding="utf-8")
    assert "live.md" in index
    assert "old.md" not in index


# ── wiki_rename: move + stub ─────────────────────────────────────────


def test_rename_creates_stub_at_old_path(tmp_wiki: Path) -> None:
    pid = generate_page_id()
    _write(tmp_wiki / "adr/_general/2234-foo.md.md", _page(pid, "Foo"))

    result = _run(
        wiki_rename.handler(
            {
                "from_path": "adr/_general/2234-foo.md.md",
                "to_path": "adr/_general/2234-foo.md",
                "reason": "slug bug cleanup",
            }
        )
    )
    assert "error" not in result, result
    assert result["page_id"] == pid
    assert result["stub_created"] is True

    # New path holds the original content.
    new_text = (tmp_wiki / "adr/_general/2234-foo.md").read_text("utf-8")
    fm = parse_frontmatter(new_text)
    assert extract_page_id(fm) == pid

    # Old path holds a redirect stub.
    stub_text = (tmp_wiki / "adr/_general/2234-foo.md.md").read_text("utf-8")
    stub_fm = parse_frontmatter(stub_text)
    assert stub_fm["redirect_to"] == "adr/_general/2234-foo.md"
    assert stub_fm["redirect_id"] == pid
    assert stub_fm["redirect_reason"] == "slug bug cleanup"


def test_rename_refuses_missing_source(tmp_wiki: Path) -> None:
    result = _run(wiki_rename.handler({"from_path": "nope.md", "to_path": "new.md"}))
    assert "error" in result
    assert "not found" in result["error"]


def test_rename_refuses_source_without_id(tmp_wiki: Path) -> None:
    _write(tmp_wiki / "no-id.md", "---\ntitle: No ID\n---\n\nbody\n")
    result = _run(wiki_rename.handler({"from_path": "no-id.md", "to_path": "new.md"}))
    assert "error" in result
    assert "lacks a valid frontmatter id" in result["error"]


def test_rename_refuses_existing_destination(tmp_wiki: Path) -> None:
    pid1 = generate_page_id()
    pid2 = generate_page_id()
    _write(tmp_wiki / "a.md", _page(pid1, "A"))
    _write(tmp_wiki / "b.md", _page(pid2, "B"))

    result = _run(wiki_rename.handler({"from_path": "a.md", "to_path": "b.md"}))
    assert "error" in result
    assert "already exists" in result["error"]


def test_rename_with_overwrite_dest(tmp_wiki: Path) -> None:
    pid1 = generate_page_id()
    pid2 = generate_page_id()
    _write(tmp_wiki / "a.md", _page(pid1, "A source"))
    _write(tmp_wiki / "b.md", _page(pid2, "B existing"))

    result = _run(
        wiki_rename.handler(
            {"from_path": "a.md", "to_path": "b.md", "overwrite_dest": True}
        )
    )
    assert "error" not in result
    # b.md now carries A's content (id and title).
    b_fm = parse_frontmatter((tmp_wiki / "b.md").read_text("utf-8"))
    assert b_fm["title"] == "A source"
    assert b_fm["id"] == pid1


def test_rename_refuses_to_chain_redirects(tmp_wiki: Path) -> None:
    """Renaming a stub onto a new path would create a stub-of-stub chain."""
    pid = generate_page_id()
    _write(tmp_wiki / "target.md", _page(pid, "Target"))
    _write(tmp_wiki / "old.md", _stub("target.md", target_id=pid))

    result = _run(wiki_rename.handler({"from_path": "old.md", "to_path": "new-old.md"}))
    assert "error" in result
    assert "already a redirect stub" in result["error"]


def test_rename_refuses_same_path(tmp_wiki: Path) -> None:
    pid = generate_page_id()
    _write(tmp_wiki / "a.md", _page(pid, "A"))
    result = _run(wiki_rename.handler({"from_path": "a.md", "to_path": "a.md"}))
    assert "error" in result


def test_rename_stub_then_read_resolves_to_target(tmp_wiki: Path) -> None:
    """End-to-end: rename + read returns the moved content via stub."""
    pid = generate_page_id()
    _write(tmp_wiki / "old.md", _page(pid, "Important"))

    _run(wiki_rename.handler({"from_path": "old.md", "to_path": "new.md"}))
    result = _run(wiki_read.handler({"path": "old.md"}))

    assert "error" not in result, result
    assert result["path"] == "new.md"
    assert "title: Important" in result["content"]
    assert result["redirect_chain"] == ["old.md", "new.md"]


def test_rename_preserves_page_body_verbatim(tmp_wiki: Path) -> None:
    pid = generate_page_id()
    body = (
        "# Title\n\n"
        "## Status\n\nAccepted\n\n"
        "## Decision\n\nDeploy pgvector.\n\n"
        "## Consequences\n\nPostgres mandatory."
    )
    full = f"---\nid: {pid}\ntitle: Title\n---\n\n{body}\n"
    _write(tmp_wiki / "old.md", full)

    _run(wiki_rename.handler({"from_path": "old.md", "to_path": "new.md"}))
    new_text = (tmp_wiki / "new.md").read_text("utf-8")
    assert body in new_text
    # Source page id survived the move.
    fm = parse_frontmatter(new_text)
    assert is_valid_page_id(extract_page_id(fm))
