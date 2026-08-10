"""Best-effort wiki-tree reindex after a write.

Split out of wiki_store.py (issue: 439 lines over the 300-line §4.1
cap, pre-existing before the layer-violation fix that also touched this
file) — regenerating ``.generated/INDEX.md``/``README.md`` and cleaning
up superseded id-prefixed pages is a distinct "post-write housekeeping"
concern from the write/read primitives (``write_page``/``read_page``)
that live in ``wiki_store.py``.
"""

from __future__ import annotations

import re as _re
from pathlib import Path

from mcp_server.observability import silent_failure
from mcp_server.shared.wiki_pages import build_index
from mcp_server.shared.wiki_readme import build_plain_readme

from mcp_server.infrastructure.wiki_pages_listing import list_pages


def _refresh_readme_if_safe(root: Path, page_paths: list[str]) -> None:
    """README half of ``try_reindex``: only overwrite if the file is
    absent or still carries the auto-generated marker — never clobber a
    hand-written README. An unreadable README also blocks the write
    (issue #197 sweep: falling through to overwrite on a read failure
    was the actual regression this guards against).
    """
    readme_path = root / "README.md"
    auto_marker = "<!-- cortex-wiki-readme: auto-generated -->"
    should_write = True
    if readme_path.exists():
        try:
            existing = readme_path.read_text()
            if auto_marker not in existing:
                should_write = False  # hand-written, don't touch
        except (OSError, UnicodeDecodeError) as exc:
            should_write = False
            silent_failure.note("wiki_store.readme_read", exc)
    if should_write:
        readme_md = build_plain_readme(page_paths)
        readme_md += f"\n{auto_marker}\n"
        readme_path.write_text(readme_md)


def try_reindex(root: Path) -> None:
    """Best-effort index rebuild after wiki write.

    Produces three artefacts:
      * ``<root>/.generated/INDEX.md`` — structured TOC grouped by
        domain then kind (for tech readers).
      * ``<root>/README.md``           — plain-language top-level
        entry point (for non-tech readers); see ``_refresh_readme_if_safe``.
      * cleans up superseded ``{id}-{slug}.md`` files via
        ``cleanup_id_prefixed_pages``.

    Called from the composition root (``mcp_server.handlers.wiki_memory_sync``)
    after a memory-promotion write, in addition to any future direct caller.
    """
    try:
        page_paths = list_pages(root)
        index_md = build_index(page_paths)
        gen_dir = root / ".generated"
        gen_dir.mkdir(exist_ok=True)
        (gen_dir / "INDEX.md").write_text(index_md)
        _refresh_readme_if_safe(root, page_paths)
        cleanup_id_prefixed_pages(root)
    except Exception as exc:  # noqa: BLE001 — index rebuild is best-effort after a write
        silent_failure.note("wiki_store.reindex", exc)


def cleanup_id_prefixed_pages(root: Path | str) -> int:
    """Remove old {id}-{slug}.md files that have a {slug}.md counterpart."""

    notes_dir = Path(root) / "notes"
    if not notes_dir.exists():
        return 0
    removed = 0
    slug_files = {
        f.name for f in notes_dir.glob("*.md") if not _re.match(r"^\d+-", f.name)
    }
    for f in list(notes_dir.glob("*.md")):
        m = _re.match(r"^(\d+)-(.+)$", f.name)
        if m and m.group(2) in slug_files:
            f.unlink()
            removed += 1
    return removed
