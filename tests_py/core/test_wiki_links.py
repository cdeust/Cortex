"""Tests for core.wiki_links — bidirectional link maintenance."""

from __future__ import annotations

import pytest

from mcp_server.core.wiki_links import (
    LinkEntry,
    RELATIONS,
    apply_link,
    inverse_of,
)


def test_inverse_of_known() -> None:
    assert inverse_of("supersedes") == "superseded_by"
    assert inverse_of("implements") == "implemented_by"
    assert inverse_of("see_also") == "see_also"


def test_inverse_of_unknown() -> None:
    with pytest.raises(KeyError):
        inverse_of("bogus")


def test_apply_link_adds_related_section() -> None:
    body = "# Title\n\nSome content.\n"
    result = apply_link(body, LinkEntry(relation="implements", target="specs/x.md"))
    assert "## Related" in result
    assert "implements → [specs/x.md](specs/x.md)" in result


def test_apply_link_is_idempotent() -> None:
    body = "# T\n\nbody\n"
    entry = LinkEntry(relation="see_also", target="notes/a.md")
    once = apply_link(body, entry)
    twice = apply_link(once, entry)
    assert once == twice


def test_apply_link_sorts_entries() -> None:
    body = "# T\n\nbody\n"
    after_a = apply_link(body, LinkEntry(relation="see_also", target="b.md"))
    after_b = apply_link(after_a, LinkEntry(relation="see_also", target="a.md"))
    a_idx = after_b.index("a.md")
    b_idx = after_b.index("b.md")
    assert a_idx < b_idx  # sorted by target after relation


def test_apply_link_preserves_trailing_sections() -> None:
    body = "# T\n\nbody\n\n## Related\n\n- see_also → [old.md](old.md)\n\n## Notes\n\ntrailing\n"
    result = apply_link(body, LinkEntry(relation="see_also", target="new.md"))
    assert "## Notes" in result
    assert "trailing" in result
    assert "old.md" in result
    assert "new.md" in result


def test_apply_link_rejects_unknown_relation() -> None:
    with pytest.raises(ValueError):
        apply_link("# x\n", LinkEntry(relation="bogus", target="a.md"))


def test_relations_all_have_inverses() -> None:
    for rel, inv in RELATIONS.items():
        assert inv in RELATIONS
        assert RELATIONS[inv] == rel
