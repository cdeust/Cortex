"""Git diff retrieval for file entities.

Runs git commands to fetch diff data for files referenced in the
knowledge graph. Uses a proper cascade: working tree → staged → last
commit → file content at HEAD → historical lookup.

Infrastructure layer — I/O via subprocess. The subprocess boundary and
argument sanitisation live in ``git_diff_exec``; the result-formatting
helpers live in ``git_diff_format``; this module owns the cascade and
the whitelist-matching policy.

Security (CWE-22 / path-injection):

  * ``_match_in_whitelist`` always returns a string drawn from the
    ``tracked`` set (``git ls-files`` output). It never returns the
    user-supplied name, even when they are ``==``. This explicitly
    breaks the taint flow so downstream uses of the returned path are
    sanitised — static analysers (CodeQL ``py/path-injection``) see
    that the returned object is not derived from user input.
  * ``_safe_join`` uses ``os.path.realpath`` + ``startswith(root +
    sep)`` containment — the canonical pattern CodeQL recognises as a
    sanitiser for path-injection.
  * Every direct filesystem probe (``is_file``, ``read_text``,
    ``exists``) goes through ``_safe_join``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from mcp_server.infrastructure.git_diff_exec import (
    _GIT_BINARY,
    get_tracked_files,
    git_cmd_safe,
)
from mcp_server.infrastructure.git_diff_format import (
    build_result,
    content_as_context,
    content_as_delete,
    content_as_new,
)


def find_git_root(start: Path | None = None) -> Path | None:
    """Find the nearest git repository root."""
    try:
        result = subprocess.run(
            [_GIT_BINARY, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=str(start) if start else None,
            timeout=5,
            shell=False,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _match_in_whitelist(name: str, tracked: set[str]) -> str | None:
    """Match a user-provided name against the git-tracked whitelist.

    Returns the canonical tracked path or ``None`` if no match. To
    break the taint flow from the caller's user-controlled ``name``,
    every return path yields a string drawn from ``tracked`` (the
    output of ``git ls-files``) — never ``name`` itself, even when
    equality holds. This is what allows static analysers to see the
    whitelist as a proper sanitiser.
    """
    basename = name.rsplit("/", 1)[-1] if "/" in name else name
    for t in tracked:
        if t == name or t == basename or t.endswith("/" + basename):
            return t
    return None


def resolve_file(name: str, git_root: Path) -> str | None:
    """Resolve a file name to a repo-relative path via the tracked whitelist."""
    clean = name.strip().strip("\"'`")
    try:
        p = Path(clean)
        if p.is_absolute():
            clean = str(p.relative_to(git_root))
    except (ValueError, OSError):
        pass

    tracked = get_tracked_files(git_root)
    match = _match_in_whitelist(clean, tracked)
    if match:
        return match

    staged = git_cmd_safe("diff", ["--staged", "--name-only"], git_root)
    if staged:
        return _match_in_whitelist(clean, set(staged.splitlines()))
    return None


def _safe_join(root: Path, relative: str) -> Path | None:
    """Join ``relative`` onto ``root`` and confirm the result stays inside.

    Uses ``os.path.realpath`` on both arguments and checks the
    canonical containment ``startswith(root + os.sep)``. This is the
    pattern CodeQL's ``py/path-injection`` query recognises as a
    sanitiser. Returns the resolved ``Path`` or ``None`` when the join
    would escape ``root`` (or raises on unresolvable input).
    """
    try:
        root_real = os.path.realpath(str(root))
        joined_real = os.path.realpath(os.path.join(root_real, relative))
    except (OSError, ValueError):
        return None
    if joined_real != root_real and not joined_real.startswith(root_real + os.sep):
        return None
    return Path(joined_real)


def _read_safe(git_root: Path, relative: str) -> str | None:
    """Read a file inside ``git_root`` safely. None for anything outside."""
    try:
        p = _safe_join(git_root, relative)
        if p is None or not p.is_file():
            return None
        return p.read_text(errors="replace")
    except OSError:
        return None


def _cascade_for_tracked(
    safe_path: str,
    tracked: set[str],
    staged_files: set[str],
    git_root: Path,
    max_lines: int,
) -> dict:
    """Run the working-tree → staged → deleted → last-commit → clean cascade."""
    raw = git_cmd_safe("diff", ["--", safe_path], git_root)
    if raw:
        return build_result(safe_path, "uncommitted", raw, max_lines)
    raw = git_cmd_safe("diff", ["--staged", "--", safe_path], git_root)
    if raw:
        return build_result(safe_path, "staged", raw, max_lines)
    # ``safe_path`` is already whitelisted against ``git ls-files``, but
    # ``_safe_join`` re-validates containment so the path-probe below is
    # provably inside the repo root (silences py/path-injection).
    abs_check = _safe_join(git_root, safe_path)
    if abs_check is None:
        return {
            "file": safe_path,
            "diff_type": "none",
            "lines": [],
            "truncated": False,
            "reason": "path escaped repo root — refusing to resolve",
        }
    if safe_path in tracked and not abs_check.exists():
        content = git_cmd_safe("show", ["HEAD:" + safe_path], git_root)
        if content:
            return content_as_delete(safe_path, content, max_lines)
    raw = git_cmd_safe("log", ["-1", "-p", "--format=", "--", safe_path], git_root)
    if raw:
        return build_result(safe_path, "last_commit", raw, max_lines)
    if safe_path in staged_files and safe_path not in tracked:
        wt = _read_safe(git_root, safe_path)
        if wt is not None:
            return content_as_new(safe_path, wt, max_lines, diff_type="staged")
    content = git_cmd_safe("show", ["HEAD:" + safe_path], git_root)
    if content:
        return content_as_context(safe_path, content, max_lines)
    return {
        "file": safe_path,
        "diff_type": "unchanged",
        "lines": [],
        "truncated": False,
        "reason": (
            "tracked by git but no content retrievable (submodule or LFS pointer)"
        ),
    }


def _staged_files_set(git_root: Path) -> set[str]:
    """Return the set of paths currently staged for commit."""
    staged_raw = git_cmd_safe("diff", ["--staged", "--name-only"], git_root)
    return set(staged_raw.splitlines()) if staged_raw else set()


def get_file_diff(filepath: str, git_root: Path, max_lines: int = 80) -> dict:
    """Cascade: tracked → untracked → historical; always non-empty result.

    Security: ``filepath`` is validated against the tracked + staged
    whitelist. Direct filesystem reads only happen for files confirmed
    by git, or for untracked files inside ``git_root`` (``_read_safe``
    uses ``Path.resolve()`` + ``is_relative_to`` to block traversal).
    """
    tracked = get_tracked_files(git_root)
    staged_files = _staged_files_set(git_root)
    safe_path = _match_in_whitelist(filepath, tracked | staged_files)
    if safe_path:
        return _cascade_for_tracked(
            safe_path, tracked, staged_files, git_root, max_lines
        )
    wt = _read_safe(git_root, filepath)
    if wt is not None:
        return content_as_new(filepath, wt, max_lines)
    historical = _lookup_historical(filepath, git_root, max_lines)
    if historical is not None:
        return historical
    return {
        "file": filepath,
        "diff_type": "none",
        "lines": [],
        "truncated": False,
        "reason": ("file not tracked, not present, and absent from all git history"),
    }


def _tier1_candidates(sha: str) -> list[str]:
    """Given the last commit touching the path, return it + its parent.

    If the commit is the deletion, the file is absent in its tree but
    present in the parent's tree (``<sha>^``).
    """
    if not sha:
        return []
    return [sha, sha + "^"]


def _deleted_result(filepath: str, content: str, max_lines: int, sha: str) -> dict:
    r = content_as_delete(filepath, content, max_lines)
    r["reason"] = f"deleted — recovered from commit {sha[:8]}"
    return r


def _try_historical_sha(
    filepath: str, git_root: Path, sha: str, max_lines: int
) -> dict | None:
    """Return a deleted_result for ``sha:filepath`` if git can show it."""
    content = git_cmd_safe("show", [sha + ":" + filepath], git_root)
    if content:
        return _deleted_result(filepath, content, max_lines, sha)
    return None


def _lookup_tier1(
    filepath: str, git_root: Path, max_lines: int
) -> tuple[dict | None, str]:
    """Tier 1: last commit touching path (follow renames) + its parent."""
    last_sha = git_cmd_safe(
        "log",
        ["-1", "--all", "--follow", "--format=%H", "--", filepath],
        git_root,
    )
    for candidate in _tier1_candidates(last_sha):
        hit = _try_historical_sha(filepath, git_root, candidate, max_lines)
        if hit is not None:
            return hit, last_sha
    return None, last_sha


def _lookup_tier2(
    filepath: str, git_root: Path, last_sha: str, max_lines: int
) -> dict | None:
    """Tier 2: explicit last non-deletion commit (``!D`` filter)."""
    alive_sha = git_cmd_safe(
        "log",
        ["-1", "--all", "--diff-filter=!D", "--format=%H", "--", filepath],
        git_root,
    )
    if alive_sha and alive_sha != last_sha:
        return _try_historical_sha(filepath, git_root, alive_sha, max_lines)
    return None


def _lookup_tier3(filepath: str, git_root: Path, max_lines: int) -> dict | None:
    """Tier 3: walk full history (cap 50) until one sha yields content."""
    all_shas = git_cmd_safe(
        "log",
        ["--all", "--follow", "--format=%H", "--", filepath],
        git_root,
    )
    if not all_shas:
        return None
    for sha_line in all_shas.splitlines()[:50]:
        sha = sha_line.strip()
        if not sha:
            continue
        hit = _try_historical_sha(filepath, git_root, sha, max_lines)
        if hit is not None:
            return hit
    return None


def _lookup_historical(filepath: str, git_root: Path, max_lines: int) -> dict | None:
    """Three-tier historical lookup for deleted / renamed paths."""
    hit, last_sha = _lookup_tier1(filepath, git_root, max_lines)
    if hit is not None:
        return hit
    hit = _lookup_tier2(filepath, git_root, last_sha, max_lines)
    if hit is not None:
        return hit
    return _lookup_tier3(filepath, git_root, max_lines)
