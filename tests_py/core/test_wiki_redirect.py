"""Tests for wiki_redirect — Phase 3 redirect stubs and resolution."""

from __future__ import annotations

import pytest

from mcp_server.core.wiki_redirect import (
    MAX_REDIRECT_DEPTH,
    Redirect,
    build_redirect_stub,
    is_redirect,
    parse_frontmatter,
    parse_redirect,
    resolve_chain,
)


_GOOD_ID = "adfb8a1f-1b58-4f0c-9a7e-4c5e6c8d9f12"
_OTHER_ID = "12345678-1234-4abc-89ab-1234567890ab"


# ── Parse ─────────────────────────────────────────────────────────────


def test_parse_path_redirect() -> None:
    fm = {"redirect_to": "adr/_general/2234-zero-dependencies.md"}
    r = parse_redirect(fm)
    assert r is not None
    assert r.target_path == "adr/_general/2234-zero-dependencies.md"
    assert r.target_id is None


def test_parse_id_redirect() -> None:
    fm = {"redirect_id": _GOOD_ID}
    r = parse_redirect(fm)
    assert r is not None
    assert r.target_id == _GOOD_ID
    assert r.is_id_based


def test_parse_both_path_and_id_preserves_both() -> None:
    fm = {"redirect_to": "new/path.md", "redirect_id": _GOOD_ID}
    r = parse_redirect(fm)
    assert r is not None
    assert r.target_path == "new/path.md"
    assert r.target_id == _GOOD_ID


def test_parse_reason_optional() -> None:
    fm = {"redirect_to": "new.md", "redirect_reason": "slug bug fix 2026-05-13"}
    r = parse_redirect(fm)
    assert r is not None
    assert r.reason == "slug bug fix 2026-05-13"


def test_parse_missing_returns_none() -> None:
    assert parse_redirect({"title": "regular page"}) is None
    assert parse_redirect({}) is None


def test_parse_empty_strings_returns_none() -> None:
    assert parse_redirect({"redirect_to": "", "redirect_id": ""}) is None


def test_parse_malformed_id_falls_back_to_path() -> None:
    """A bad UUID in redirect_id with a valid path is still usable."""
    fm = {"redirect_to": "new.md", "redirect_id": "not-a-uuid"}
    r = parse_redirect(fm)
    assert r is not None
    assert r.target_path == "new.md"
    assert r.target_id is None


def test_parse_malformed_id_alone_returns_none() -> None:
    """A bad UUID with no path is unrecoverable — treat as no redirect."""
    assert parse_redirect({"redirect_id": "not-a-uuid"}) is None


# ── Redirect dataclass ────────────────────────────────────────────────


def test_redirect_requires_target() -> None:
    with pytest.raises(ValueError, match="requires at least one"):
        Redirect()


def test_redirect_rejects_invalid_id() -> None:
    with pytest.raises(ValueError, match="invalid redirect_id"):
        Redirect(target_path="x.md", target_id="not-a-uuid")


def test_is_redirect_helper() -> None:
    assert is_redirect({"redirect_to": "x.md"})
    assert is_redirect({"redirect_id": _GOOD_ID})
    assert not is_redirect({"title": "regular"})


# ── Chain resolution ──────────────────────────────────────────────────


def _make_reader(graph: dict[str, dict[str, object]]):
    """Build a FrontmatterReader callable backed by a path→frontmatter dict."""

    def _reader(path: str) -> dict[str, object]:
        return graph.get(path, {})

    return _reader


def test_resolve_chain_no_redirect() -> None:
    """A non-redirect page resolves to itself with 0 hops."""
    reader = _make_reader({"foo.md": {"title": "Foo"}})
    result = resolve_chain("foo.md", reader)
    assert result is not None
    assert result.final_path == "foo.md"
    assert result.hops == 0
    assert result.chain == ("foo.md",)


def test_resolve_chain_single_hop() -> None:
    reader = _make_reader(
        {
            "old.md": {"redirect_to": "new.md"},
            "new.md": {"title": "New home"},
        }
    )
    result = resolve_chain("old.md", reader)
    assert result is not None
    assert result.final_path == "new.md"
    assert result.hops == 1
    assert result.chain == ("old.md", "new.md")


def test_resolve_chain_multi_hop() -> None:
    """A chain of redirects (rename → rename) resolves to the terminal page."""
    reader = _make_reader(
        {
            "v1.md": {"redirect_to": "v2.md"},
            "v2.md": {"redirect_to": "v3.md"},
            "v3.md": {"title": "Final"},
        }
    )
    result = resolve_chain("v1.md", reader)
    assert result is not None
    assert result.final_path == "v3.md"
    assert result.hops == 2


def test_resolve_chain_cycle_returns_none() -> None:
    reader = _make_reader(
        {
            "a.md": {"redirect_to": "b.md"},
            "b.md": {"redirect_to": "a.md"},
        }
    )
    assert resolve_chain("a.md", reader) is None


def test_resolve_chain_self_loop_returns_none() -> None:
    reader = _make_reader({"loop.md": {"redirect_to": "loop.md"}})
    assert resolve_chain("loop.md", reader) is None


def test_resolve_chain_depth_limit() -> None:
    """A chain longer than MAX_REDIRECT_DEPTH returns None.

    Defensive: keeps adversarial or accidental long chains from hanging
    the reader.
    """
    graph: dict[str, dict[str, object]] = {}
    for i in range(MAX_REDIRECT_DEPTH + 3):
        graph[f"hop{i}.md"] = {"redirect_to": f"hop{i + 1}.md"}
    reader = _make_reader(graph)
    assert resolve_chain("hop0.md", reader) is None


def test_resolve_chain_id_only_redirect_returns_none() -> None:
    """The path-based resolver cannot follow an ID-only redirect."""
    reader = _make_reader({"old.md": {"redirect_id": _GOOD_ID}})
    assert resolve_chain("old.md", reader) is None


# ── Stub authoring ────────────────────────────────────────────────────


def test_build_stub_with_path_only() -> None:
    md = build_redirect_stub(target_path="new/path.md", target_title="The new home")
    assert "redirect_to: new/path.md" in md
    assert "[The new home](new/path.md)" in md
    assert "redirect_id" not in md


def test_build_stub_with_id_and_path() -> None:
    md = build_redirect_stub(
        target_path="new.md",
        target_id=_GOOD_ID,
        target_title="ADR-1",
        reason="slug bug fix",
        created_at="2026-05-13T10:00:00Z",
    )
    assert f"redirect_id: {_GOOD_ID}" in md
    assert "redirect_to: new.md" in md
    assert "redirect_reason: slug bug fix" in md
    assert "created: 2026-05-13T10:00:00Z" in md


def test_build_stub_id_only() -> None:
    md = build_redirect_stub(target_id=_GOOD_ID, target_title="ADR-1")
    assert f"redirect_id: {_GOOD_ID}" in md
    assert "ADR-1" in md


def test_build_stub_rejects_no_target() -> None:
    with pytest.raises(ValueError, match="target_path or target_id"):
        build_redirect_stub()


def test_build_stub_rejects_invalid_id() -> None:
    with pytest.raises(ValueError, match="invalid target_id"):
        build_redirect_stub(target_id="not-a-uuid")


def test_build_stub_roundtrips_through_parse() -> None:
    """The stub we write parses back into a Redirect we can resolve."""
    md = build_redirect_stub(
        target_path="new.md",
        target_id=_GOOD_ID,
        reason="cleanup",
    )
    fm = parse_frontmatter(md)
    r = parse_redirect(fm)
    assert r is not None
    assert r.target_path == "new.md"
    assert r.target_id == _GOOD_ID
    assert r.reason == "cleanup"


# ── Frontmatter parser sanity (shared with the pilot) ─────────────────


def test_parse_frontmatter_scalar_inline_list_block_list() -> None:
    text = (
        "---\n"
        "title: Mixed\n"
        "inline: [a, b, c]\n"
        "tags:\n"
        "  - first\n"
        "  - second\n"
        "---\n\n"
        "Body\n"
    )
    fm = parse_frontmatter(text)
    assert fm["title"] == "Mixed"
    assert fm["inline"] == ["a", "b", "c"]
    assert fm["tags"] == ["first", "second"]


def test_parse_frontmatter_no_delimiter() -> None:
    assert parse_frontmatter("just body, no frontmatter") == {}
