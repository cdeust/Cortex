"""Wiki filesystem store — read/write primitives, never destructive.

Operations:
    read_page       return the raw markdown or None if missing
    write_page      atomic write in create/append/replace modes

Never deletes pages. Never regenerates content. Page listing/append
(``append_section``/``list_pages``/``next_adr_number``) lives in the
sibling ``wiki_pages_listing`` module and reindex (``.generated/
INDEX.md``/``README.md`` rebuild + superseded-page cleanup) in
``wiki_reindex_io`` — both split out (issue: 439 lines over the
300-line §4.1 cap, pre-existing before the layer-violation fix that
also touched this file).

Issue #110: ``write_page`` is the true choke point for every wiki-tree
byte, not ``wiki_write.write_governed_page`` (that function's docstring
claimed otherwise pre-fix; corrected there). At least 7 handlers call
``write_page`` directly, bypassing ``write_governed_page``'s governance
side effects (pointer memory, citations) — deliberately, in most cases
(e.g. redirect stubs, generated reference pages) where that bookkeeping
does not apply. What those callers must NOT be able to bypass is
write-time frontmatter normalization (issue #107/PR #109): ``write_page``
itself now runs ``normalize_frontmatter`` on any full-page write
(``create``/``replace``; ``append``'s content is a fragment, never
normalized — same exclusion ``write_governed_page`` already documented),
so no caller, present or future, can persist a non-canonical frontmatter
shape.

Layer note: this module's page-write dependency (``normalize_frontmatter``)
is pure, zero-I/O and lives in ``shared/`` (moved from ``core/``, issue:
infra may not import core). Promoting a memory to a wiki page DOES need
real domain judgment (the v2 classifier, ``core.wiki_sync.build_from_memory``)
— that call is made by the composition root,
``mcp_server.handlers.wiki_memory_sync``, which wires this module's
``write_page`` (pure I/O) to core's classification decision. This
module itself never imports ``core/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mcp_server.shared.wiki_frontmatter_validation import normalize_frontmatter
import os

WriteMode = str  # "create" | "append" | "replace"


@dataclass(frozen=True)
class WriteResult:
    path: str
    mode: str
    created: bool
    bytes_written: int


class WikiExistsError(Exception):
    """Raised when ``create`` mode finds an existing file."""


class WikiMissingError(Exception):
    """Raised when ``append`` mode targets a missing file."""


def safe_join(root: Path, rel_path: str) -> Path:
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
    any failure. Public (not ``_``-prefixed): called from the sibling
    ``wiki_pages_listing`` module in addition to this one.
    """

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


def read_page(root: Path | str, rel_path: str) -> str | None:

    # CWE-22 sanitization. Structure matches CodeQL's py/path-injection
    # example VERBATIM so the sanitizer is unambiguously recognised:
    #   base_path = os.path.realpath(root)  # noqa: ERA001
    #   fullpath = os.path.realpath(os.path.join(base_path, user_input))  # noqa: ERA001
    #   if not fullpath.startswith(base_path): ...  # noqa: ERA001
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


def write_page(
    root: Path | str,
    rel_path: str,
    content: str,
    *,
    mode: WriteMode = "create",
) -> WriteResult:
    """Write a page atomically.

    * ``create`` — raises WikiExistsError if the file already exists.
    * ``replace`` — overwrites regardless.
    * ``append`` — appends the content to the existing file (with a
      separating blank line), raises WikiMissingError if the file does not exist.

    precondition: for ``create``/``replace``, ``content`` is a FULL page
    (frontmatter + body, or plain body with no frontmatter) the caller
    intends to persist verbatim; for ``append``, ``content`` is a
    fragment appended below whatever is already on disk.
    postcondition: for ``create``/``replace``, the bytes actually written
    are always ``normalize_frontmatter(content)`` (issue #110) — this is
    the one choke point every wiki-tree write passes through, so no
    caller (governed via ``write_governed_page`` or direct) can persist a
    non-canonical frontmatter shape. ``append``'s fragment is never
    normalized (there is no frontmatter fence to canonicalize in a
    fragment, and treating one as a full page would corrupt it — see
    ``normalize_frontmatter``'s own precondition).
    raises: ``UnclosedFrontmatterError`` (from ``normalize_frontmatter``,
    propagated uncaught) for ``create``/``replace`` when ``content`` opens
    a frontmatter fence it never closes.
    """
    fullpath = _resolve_write_target(root, rel_path)
    if mode != "append":
        content = normalize_frontmatter(content)
    # fullpath is sanitized — use it directly at every sink.
    existed = os.path.exists(fullpath)
    written = _write_by_mode(fullpath, rel_path, content, mode, existed)
    return WriteResult(
        path=rel_path, mode=mode, created=not existed, bytes_written=written
    )


def _resolve_write_target(root: Path | str, rel_path: str) -> str:
    """CWE-22 sanitization matching CodeQL's py/path-injection example
    VERBATIM (see ``read_page`` for references). Returns the sanitized
    absolute path string for ``write_page`` to use at every sink.
    """
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
    return fullpath


def _write_by_mode(
    fullpath: str, rel_path: str, content: str, mode: WriteMode, existed: bool
) -> int:
    """Perform the create/replace/append write ``write_page`` decided on.

    ``fullpath`` is already sanitized by ``_resolve_write_target``.
    Returns the number of bytes written.
    """
    if mode == "create":
        if existed:
            raise WikiExistsError(rel_path)
        return _atomic_write_bytes_str(fullpath, content)
    if mode == "replace":
        return _atomic_write_bytes_str(fullpath, content)
    if mode == "append":
        if not existed:
            raise WikiMissingError(rel_path)
        with open(fullpath, encoding="utf-8") as f:
            current = f.read()
        if current and not current.endswith("\n"):
            current += "\n"
        merged = current + "\n" + content
        if not merged.endswith("\n"):
            merged += "\n"
        return _atomic_write_bytes_str(fullpath, merged)
    raise ValueError(f"unknown write mode: {mode}")


def _atomic_write_bytes_str(safe_path: str, content: str) -> int:
    """Write ``content`` atomically to an ALREADY-SANITIZED path string.

    Separate from ``_atomic_write_bytes`` so the string-based flow from
    ``write_page`` doesn't rebind through ``Path(...)`` — keeps the
    sanitizer→sink chain on the same variable for static analysis.
    """

    parent = os.path.dirname(safe_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    tmp = safe_path + ".tmp"
    data = content.encode("utf-8")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, safe_path)
    return len(data)
