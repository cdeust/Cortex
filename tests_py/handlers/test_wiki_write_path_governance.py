"""Issue #110: write-time frontmatter normalization now applies to every
``write_page`` caller, not just the governed ``wiki_write`` tool path.

These tests exercise two of the direct (governance-bypassing) callers —
``wiki_adr`` and ``wiki_link`` — end to end through their real handlers,
proving the normalization boundary moved down to
``infrastructure.wiki_store.write_page`` actually covers them. See
``tests_py/architecture/test_write_page_call_sites.py`` for the audited
whitelist of every direct caller, and
``tests_py/handlers/test_wiki_write_frontmatter_validation.py`` for the
equivalent coverage of the governed path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mcp_server.handlers import wiki_adr, wiki_link


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── wiki_adr: a corrupted rendered ADR is persisted canonically ──────────


def test_wiki_adr_persists_corrupted_content_canonically(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(wiki_adr, "WIKI_ROOT", str(tmp_path))

    async def _noop_pointer_memory(*_a, **_kw):
        return None

    monkeypatch.setattr(wiki_adr, "_store_pointer_memory", _noop_pointer_memory)

    corrupt_content = (
        "---\n"
        'title: title: "Some decision"\n'
        "kind: adr\n"
        "status: accepted\n"
        "---\n\n# ADR-0001: Some decision\n\nBody.\n"
    )
    monkeypatch.setattr(wiki_adr, "build_adr", lambda **_kw: corrupt_content)

    result = _run(
        wiki_adr.handler(
            {
                "title": "Some decision",
                "context": "ctx",
                "decision": "dec",
                "consequences": "cons",
            }
        )
    )

    assert "error" not in result
    on_disk = (tmp_path / result["path"]).read_text(encoding="utf-8")
    assert "title: title:" not in on_disk
    assert "title: Some decision" in on_disk


# ── wiki_link: linking a pre-existing corrupted page canonicalizes it ────


def test_wiki_link_persists_corrupted_page_canonically(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(wiki_link, "WIKI_ROOT", str(tmp_path))

    from_dir = tmp_path / "notes"
    from_dir.mkdir(parents=True)
    corrupt_content = (
        '---\ntitle: title: "Corrupted source page"\nkind: note\n---\n\nBody text.\n'
    )
    (from_dir / "a.md").write_text(corrupt_content, encoding="utf-8")
    (from_dir / "b.md").write_text(
        "---\ntitle: Clean target page\nkind: note\n---\n\nOther body.\n",
        encoding="utf-8",
    )

    result = _run(
        wiki_link.handler(
            {
                "from_path": "notes/a.md",
                "to_path": "notes/b.md",
                "relation": "see_also",
            }
        )
    )

    assert "error" not in result
    on_disk_a = (from_dir / "a.md").read_text(encoding="utf-8")
    assert "title: title:" not in on_disk_a
    assert "title: Corrupted source page" in on_disk_a
    assert "## Related" in on_disk_a
    assert "notes/b.md" in on_disk_a


# ── append_section (a distinct write_page-adjacent function) is unaffected ─


def test_append_section_unchanged_by_normalization(tmp_path: Path) -> None:
    """append_section never calls write_page (it uses its own atomic-write
    helper), so it is out of scope for issue #110's normalization gate —
    confirm behavior is unchanged: no frontmatter round-trip, fragment
    appended verbatim under the target heading."""
    from mcp_server.infrastructure.wiki_store import append_section, write_page

    write_page(
        tmp_path,
        "notes/c.md",
        '---\ntitle: title: "Still corrupted"\nkind: note\n---\n\nBody.\n',
        mode="create",
    )
    # write_page itself normalizes on the way in (issue #110) — start from
    # the canonical form so this test isolates append_section's own
    # behavior rather than re-testing write_page's gate.
    before = (tmp_path / "notes/c.md").read_text(encoding="utf-8")
    assert "title: title:" not in before

    result = append_section(tmp_path, "notes/c.md", "Notes", "A new fragment.")

    assert result.mode == "append-section"
    after = (tmp_path / "notes/c.md").read_text(encoding="utf-8")
    assert after.startswith(before.rstrip("\n"))
    assert "## Notes" in after
    assert "A new fragment." in after
