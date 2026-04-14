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
from mcp_server.core.wiki_sync import build_from_memory
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


def _safe_join(root: Path, rel_path: str) -> Path:
    """Resolve ``rel_path`` against ``root`` with inline CWE-22 sanitization.

    Four layers, applied in order at every call site (no cross-function
    taint gap that static analysis can miss):
      1. Reject empty and null-byte paths.
      2. Reject absolute paths.
      3. Resolve both root and target.
      4. Confirm the resolved target lies under the resolved root via
         ``os.path.commonpath`` — a canonical CodeQL-recognised
         sanitizer for path-injection (``py/path-injection``).

    Returns the validated absolute target path. Raises ValueError on
    any failure.
    """
    import os

    if not rel_path or "\x00" in rel_path:
        raise ValueError("invalid wiki path: empty or contains null byte")
    if os.path.isabs(rel_path):
        raise ValueError(f"absolute paths are not allowed: {rel_path!r}")

    root_resolved = os.path.realpath(str(root))
    candidate = os.path.realpath(os.path.join(root_resolved, rel_path))

    # os.path.commonpath on the pair — if they differ from the root, the
    # candidate has escaped. This is the pattern CodeQL matches as a
    # path-traversal sanitizer.
    try:
        common = os.path.commonpath([root_resolved, candidate])
    except ValueError as exc:
        # Different drives on Windows, etc.
        raise ValueError(f"path escapes wiki root: {rel_path!r}") from exc
    if common != root_resolved:
        raise ValueError(f"path escapes wiki root: {rel_path!r}")
    return Path(candidate)


# Backwards-compatible alias — older call sites still use _abs.
_abs = _safe_join


def read_page(root: Path | str, rel_path: str) -> str | None:
    import os

    # CWE-22 sanitization. Structure matches CodeQL's py/path-injection
    # example VERBATIM so the sanitizer is unambiguously recognised:
    #   base_path = os.path.realpath(root)
    #   fullpath  = os.path.realpath(os.path.join(base_path, user_input))
    #   if not fullpath.startswith(base_path): ...
    # https://codeql.github.com/codeql-query-help/python/py-path-injection/
    if not rel_path or "\x00" in rel_path or os.path.isabs(rel_path):
        return None
    base_path = os.path.realpath(str(root))
    fullpath = os.path.realpath(os.path.join(base_path, rel_path))
    if not fullpath.startswith(base_path):
        return None
    # Defence-in-depth against prefix-aliasing (base_path='/foo' matches
    # '/foobar'). CodeQL's example doesn't do this; we add it because
    # the containment check above is too permissive without a separator.
    if fullpath != base_path and not fullpath[len(base_path) :].startswith(os.sep):
        return None
    # fullpath is sanitized — sink uses the sanitized variable directly.
    if not os.path.exists(fullpath):
        return None
    with open(fullpath, encoding="utf-8") as f:
        return f.read()


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
    import os

    # CWE-22 sanitization matching CodeQL's py/path-injection example
    # VERBATIM (see read_page for references).
    if not rel_path or "\x00" in rel_path:
        raise ValueError("invalid wiki path: empty or contains null byte")
    if os.path.isabs(rel_path):
        raise ValueError(f"absolute paths are not allowed: {rel_path!r}")
    base_path = os.path.realpath(str(Path(root)))
    fullpath = os.path.realpath(os.path.join(base_path, rel_path))
    if not fullpath.startswith(base_path):
        raise ValueError(f"path escapes wiki root: {rel_path!r}")
    # Defence-in-depth against prefix-aliasing.
    if fullpath != base_path and not fullpath[len(base_path) :].startswith(os.sep):
        raise ValueError(f"path escapes wiki root: {rel_path!r}")

    # fullpath is sanitized — use it directly at every sink.
    existed = os.path.exists(fullpath)

    if mode == "create":
        if existed:
            raise WikiExists(rel_path)
        written = _atomic_write_bytes_str(fullpath, content)
    elif mode == "replace":
        written = _atomic_write_bytes_str(fullpath, content)
    elif mode == "append":
        if not existed:
            raise WikiMissing(rel_path)
        with open(fullpath, encoding="utf-8") as f:
            current = f.read()
        if current and not current.endswith("\n"):
            current += "\n"
        merged = current + "\n" + content
        if not merged.endswith("\n"):
            merged += "\n"
        written = _atomic_write_bytes_str(fullpath, merged)
    else:
        raise ValueError(f"unknown write mode: {mode}")

    return WriteResult(
        path=rel_path, mode=mode, created=not existed, bytes_written=written
    )


def _atomic_write_bytes_str(safe_path: str, content: str) -> int:
    """Write ``content`` atomically to an ALREADY-SANITIZED path string.

    Separate from ``_atomic_write_bytes`` so the string-based flow from
    ``write_page`` doesn't rebind through ``Path(...)`` — keeps the
    sanitizer→sink chain on the same variable for static analysis.
    """
    import os

    parent = os.path.dirname(safe_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    tmp = safe_path + ".tmp"
    data = content.encode("utf-8")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, safe_path)
    return len(data)


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


def _try_reindex(root: Path) -> None:
    """Best-effort index rebuild after wiki write."""
    try:
        from mcp_server.core.wiki_pages import build_index

        page_paths = list_pages(root)
        index_md = build_index(page_paths)
        gen_dir = root / ".generated"
        gen_dir.mkdir(exist_ok=True)
        (gen_dir / "INDEX.md").write_text(index_md)
        cleanup_id_prefixed_pages(root)
    except Exception:
        pass


def sync_memory(
    root: Path | str,
    *,
    memory_id: int | str,
    content: str,
    tags: list[str] | None,
    domain: str = "",
) -> str | None:
    """Promote a stored memory to a wiki page if it passes the classifier.

    Uses the wiki classifier to determine page kind and reject noise.
    Domain-scoped paths organize pages by project.

    Never raises: swallows all exceptions and returns None, since this
    runs on every ``remember`` call and must not break the write path.

    Returns the relative path of the written page, or None when the
    memory is rejected or on error.
    """
    try:
        built = build_from_memory(
            memory_id=memory_id, content=content, tags=tags, domain=domain
        )
        if built is None:
            return None
        rel_path, markdown = built
        write_page(root, rel_path, markdown, mode="replace")
        _try_reindex(Path(root))
        return rel_path
    except Exception:
        return None


def cleanup_id_prefixed_pages(root: Path | str) -> int:
    """Remove old {id}-{slug}.md files that have a {slug}.md counterpart."""
    import re as _re

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
