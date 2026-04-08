"""Wiki filesystem store — authoring primitives, never destructive.

Operations:
    read_page       return the raw markdown or None if missing
    write_page      atomic write in create/append/replace modes
    append_section  append text under a named ``## Section``
    list_pages      enumerate pages, optionally filtered by kind
    next_adr_number find the next free ADR sequence number

Never deletes pages. Never regenerates content. The only file that may
be overwritten by regeneration is ``.generated/INDEX.md`` (owned by the
wiki_reindex handler, not this module).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mcp_server.core.wiki_layout import PAGE_KINDS
from mcp_server.infrastructure.file_io import ensure_dir

WriteMode = str  # "create" | "append" | "replace"


@dataclass(frozen=True)
class WriteResult:
    path: str
    mode: str
    created: bool
    bytes_written: int


class WikiExists(Exception):
    """Raised when ``create`` mode finds an existing file."""


class WikiMissing(Exception):
    """Raised when ``append`` mode targets a missing file."""


def _abs(root: Path, rel_path: str) -> Path:
    target = (root / rel_path).resolve()
    root_resolved = root.resolve()
    if root_resolved not in target.parents and target != root_resolved:
        raise ValueError(f"path escapes wiki root: {rel_path}")
    return target


def read_page(root: Path | str, rel_path: str) -> str | None:
    target = _abs(Path(root), rel_path)
    if not target.exists():
        return None
    return target.read_text(encoding="utf-8")


def _atomic_write_bytes(target: Path, content: str) -> int:
    ensure_dir(target.parent)
    tmp = target.with_suffix(target.suffix + ".tmp")
    data = content.encode("utf-8")
    tmp.write_bytes(data)
    tmp.replace(target)
    return len(data)


def write_page(
    root: Path | str,
    rel_path: str,
    content: str,
    *,
    mode: WriteMode = "create",
) -> WriteResult:
    """Write a page atomically.

    * ``create`` — raises WikiExists if the file already exists.
    * ``replace`` — overwrites regardless.
    * ``append`` — appends the content to the existing file (with a
      separating blank line), raises WikiMissing if the file does not exist.
    """
    target = _abs(Path(root), rel_path)
    existed = target.exists()

    if mode == "create":
        if existed:
            raise WikiExists(rel_path)
        written = _atomic_write_bytes(target, content)
    elif mode == "replace":
        written = _atomic_write_bytes(target, content)
    elif mode == "append":
        if not existed:
            raise WikiMissing(rel_path)
        current = target.read_text(encoding="utf-8")
        if current and not current.endswith("\n"):
            current += "\n"
        merged = current + "\n" + content
        if not merged.endswith("\n"):
            merged += "\n"
        written = _atomic_write_bytes(target, merged)
    else:
        raise ValueError(f"unknown write mode: {mode}")

    return WriteResult(
        path=rel_path, mode=mode, created=not existed, bytes_written=written
    )


def append_section(
    root: Path | str,
    rel_path: str,
    heading: str,
    content: str,
) -> WriteResult:
    """Append text under a ``## heading`` section, creating it if missing."""
    target = _abs(Path(root), rel_path)
    if not target.exists():
        raise WikiMissing(rel_path)
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
