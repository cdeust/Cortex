"""Wiki writer — atomic filesystem sync for wiki pages.

Owns the wiki root directory. Writes pages produced by core.wiki_projection
and prunes any orphan files no longer in the projection. No domain logic.

Idempotent: writing identical content is a no-op (mtime is preserved when
content hash is unchanged). Atomic per-file via tmp + rename.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from mcp_server.core.wiki_projection import WikiPage
from mcp_server.infrastructure.file_io import ensure_dir


@dataclass(frozen=True)
class SyncResult:
    written: int
    skipped: int
    pruned: int
    root: str


def _atomic_write(target: Path, content: str) -> bool:
    """Write content to target atomically. Returns True if file changed."""
    if target.exists():
        try:
            if target.read_text(encoding="utf-8") == content:
                return False
        except OSError:
            pass
    ensure_dir(target.parent)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(target)
    return True


def _collect_existing(root: Path) -> set[Path]:
    if not root.exists():
        return set()
    return {p for p in root.rglob("*.md") if p.is_file()}


def _prune_orphans(root: Path, kept: set[Path]) -> int:
    pruned = 0
    for existing in _collect_existing(root):
        if existing not in kept:
            try:
                existing.unlink()
                pruned += 1
            except OSError:
                pass
    # Remove empty directories left behind, deepest-first.
    if root.exists():
        for d in sorted(
            (p for p in root.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts),
            reverse=True,
        ):
            try:
                d.rmdir()
            except OSError:
                pass
    return pruned


def sync(
    root: Path | str,
    pages: Iterable[WikiPage],
    *,
    dry_run: bool = False,
) -> SyncResult:
    """Write pages under root, pruning anything no longer projected."""
    root_path = Path(root)
    page_list = list(pages)
    kept: set[Path] = set()
    written = 0
    skipped = 0

    if dry_run:
        for page in page_list:
            target = root_path / Path(str(page.path))
            kept.add(target)
            if target.exists() and target.read_text(encoding="utf-8") == page.markdown:
                skipped += 1
            else:
                written += 1
        existing = _collect_existing(root_path)
        pruned = sum(1 for e in existing if e not in kept)
        return SyncResult(written, skipped, pruned, str(root_path))

    ensure_dir(root_path)
    for page in page_list:
        target = root_path / Path(str(page.path))
        kept.add(target)
        if _atomic_write(target, page.markdown):
            written += 1
        else:
            skipped += 1

    pruned = _prune_orphans(root_path, kept)
    return SyncResult(written, skipped, pruned, str(root_path))
