"""Wiki page listing + append-in-place: ``append_section``, ``list_pages``,
``next_adr_number``.

Split out of wiki_store.py (issue: 439 lines over the 300-line §4.1
cap, pre-existing before the layer-violation fix that also touched
that file) — enumerating/appending to already-written pages is a
distinct concern from the create/replace write path
(``wiki_store.write_page``) and from reindex housekeeping
(``wiki_reindex_io``).
"""

from __future__ import annotations

from pathlib import Path

from mcp_server.shared.wiki_layout import PAGE_KINDS
from mcp_server.infrastructure.file_io import ensure_dir

from mcp_server.infrastructure.wiki_store import (
    WikiMissingError,
    WriteResult,
    safe_join,
)


def _atomic_write_bytes(target: Path, content: str) -> int:
    ensure_dir(target.parent)
    tmp = target.with_suffix(target.suffix + ".tmp")
    data = content.encode("utf-8")
    tmp.write_bytes(data)
    tmp.replace(target)
    return len(data)


def append_section(
    root: Path | str,
    rel_path: str,
    heading: str,
    content: str,
) -> WriteResult:
    """Append text under a ``## heading`` section, creating it if missing."""
    target = safe_join(Path(root), rel_path)
    if not target.exists():
        raise WikiMissingError(rel_path)
    current = target.read_text(encoding="utf-8")
    heading_line = f"## {heading}"
    if heading_line in current:
        # Append at the end of the file — simplest semantics; the heading is
        # reused, not duplicated, but the new content goes after whatever is
        # already there.
        if not current.endswith("\n"):
            current += "\n"
        merged = f"{current}\n{content}\n"
    else:
        if current and not current.endswith("\n"):
            current += "\n"
        merged = f"{current}\n{heading_line}\n\n{content}\n"
    written = _atomic_write_bytes(target, merged)
    return WriteResult(
        path=rel_path, mode="append-section", created=False, bytes_written=written
    )


def list_pages(root: Path | str, *, kind: str | None = None) -> list[str]:
    """Enumerate authored pages relative to the wiki root.

    Skips ``.generated/``. If ``kind`` is supplied, only returns pages
    under ``<root>/<kind>/``. Output is sorted for determinism.
    """
    root_path = Path(root)
    if not root_path.exists():
        return []
    kinds = (kind,) if kind else PAGE_KINDS
    results: list[str] = []
    for k in kinds:
        if k not in PAGE_KINDS:
            continue
        kind_dir = root_path / k
        if not kind_dir.exists():
            continue
        for p in sorted(kind_dir.rglob("*.md")):
            results.append(str(p.relative_to(root_path)).replace("\\", "/"))
    return results


def next_adr_number(root: Path | str) -> int:
    """Return the next free ADR sequence number (1-based)."""
    pages = list_pages(root, kind="adr")
    max_seen = 0
    for rel in pages:
        name = rel.rsplit("/", 1)[-1]
        # NNNN-slug.md
        head = name.split("-", 1)[0]
        try:
            num = int(head)
        except ValueError:
            continue
        if num > max_seen:
            max_seen = num
    return max_seen + 1
