"""Issue #107: write_governed_page validates/normalizes frontmatter at
write time instead of persisting caller-supplied markdown verbatim.

Mirrors test_wiki_write_citations.py's fixture approach (fake PG
collaborators, real tmp_path wiki root, real write_page/write_governed_page
code path) so these assertions exercise the actual disk-write, not a mock.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from mcp_server.handlers import wiki_write


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture
def tmp_wiki(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(wiki_write, "WIKI_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture(autouse=True)
def _no_pg(monkeypatch):
    """These tests only care about the on-disk bytes; degrade the
    best-effort PG side effects to no-ops (same contract the citations
    test suite already relies on: page-sync/citation failure never blocks
    the write)."""

    def _boom(*a, **kw):
        raise RuntimeError("no PG in this test")

    monkeypatch.setattr(wiki_write, "get_shared_store", _boom)


# ── (a) corrupted duplicated-label frontmatter is persisted canonically ──


def test_duplicated_label_frontmatter_persisted_canonically(tmp_wiki) -> None:
    corrupt_content = (
        "---\n"
        'title: title: "Public API surface: automatised-pipeline"\n'
        "kind: reference\n"
        "---\n\nBody text.\n"
    )

    result = _run(
        wiki_write.handler({"path": "reference/a.md", "content": corrupt_content})
    )

    assert "error" not in result
    on_disk = (tmp_wiki / "reference/a.md").read_text(encoding="utf-8")
    assert "title: title:" not in on_disk
    assert "title: Public API surface: automatised-pipeline" in on_disk


# ── (b) a healthy page round-trips byte-identical (idempotence) ──────────


def test_healthy_page_persisted_unchanged(tmp_wiki) -> None:
    from mcp_server.shared.wiki_pages import build_note

    healthy_content = build_note(title="Clean note", body="Nothing to repair.")

    result = _run(
        wiki_write.handler({"path": "notes/clean.md", "content": healthy_content})
    )

    assert "error" not in result
    on_disk = (tmp_wiki / "notes/clean.md").read_text(encoding="utf-8")
    assert on_disk == healthy_content


# ── (c) structurally inexploitable frontmatter is rejected with ToolError ─


def test_unclosed_frontmatter_fence_raises_tool_error(tmp_wiki) -> None:
    """Calling wiki_write.handler directly raises the plain
    UnclosedFrontmatterError (a ValueError) — the handler itself never
    imports fastmcp. The ToolError conversion is the repo's standing
    safe_handler idiom (commits c7dfc243/49f29e98): any exception a
    handler raises becomes a ToolError at the tool-registration boundary,
    verified here the same way test_remember.py pins the dict contract.
    """
    from mcp_server.shared.wiki_frontmatter_validation import UnclosedFrontmatterError
    from mcp_server.tool_error_handler import safe_handler

    unclosed_content = (
        "---\ntitle: Something\nkind: note\n\nThis was meant to be the body.\n"
    )

    with pytest.raises(UnclosedFrontmatterError):
        _run(
            wiki_write.handler({"path": "notes/broken.md", "content": unclosed_content})
        )
    assert not (tmp_wiki / "notes/broken.md").exists()

    with pytest.raises(ToolError):
        _run(
            safe_handler(
                wiki_write.handler,
                {"path": "notes/broken2.md", "content": unclosed_content},
                tool_name="wiki_write",
            )
        )
    assert not (tmp_wiki / "notes/broken2.md").exists()


# ── append mode is a fragment, not a full page — never normalized ────────


def test_append_mode_content_is_never_frontmatter_normalized(tmp_wiki) -> None:
    _run(wiki_write.handler({"path": "notes/x.md", "content": "# X\n\nInitial.\n"}))

    result = _run(
        wiki_write.handler(
            {
                "path": "notes/x.md",
                "content": "---\nnot: closed",
                "mode": "append",
            }
        )
    )

    assert "error" not in result
    on_disk = (tmp_wiki / "notes/x.md").read_text(encoding="utf-8")
    assert "---\nnot: closed" in on_disk
