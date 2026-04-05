"""Git diff retrieval for file entities.

Runs git commands to fetch diff data for files referenced in the
knowledge graph. Uses a proper cascade: working tree -> staged ->
last commit -> file content at HEAD.

Infrastructure layer - I/O via subprocess.

References:
- https://git-scm.com/docs/git-diff
- https://git-scm.com/docs/git-log
- https://graphite.com/guides/git-diff-not-showing-anything
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def find_git_root(start: Path | None = None) -> Path | None:
    """Find the nearest git repository root."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=str(start) if start else None,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def resolve_file(name: str, git_root: Path) -> str | None:
    """Resolve a file name/path to a repo-relative path.

    Handles absolute paths, relative paths, and bare filenames.
    Uses git ls-files for verification.
    """
    rel = _to_relative(name, git_root)
    if not rel:
        # Invalid or unsafe path (outside repo, traversal, etc.)
        return None

    # Check if it's tracked by git
    tracked = _git_cmd(["git", "ls-files", "--", rel], git_root)
    if tracked:
        return tracked.splitlines()[0]

    # Check if it's a new staged file
    staged = _git_cmd(["git", "diff", "--staged", "--name-only", "--", rel], git_root)
    if staged:
        return staged.splitlines()[0]

    # Try basename search across all tracked files
    basename = Path(rel).name
    all_files = _git_cmd(["git", "ls-files"], git_root)
    if all_files:
        for f in all_files.splitlines():
            if f.endswith("/" + basename) or f == basename:
                return f

    # File exists on disk but untracked
    full = git_root / rel
    if full.is_file():
        return rel

    return None


def get_file_diff(filepath: str, git_root: Path, max_lines: int = 80) -> dict:
    """Get diff for a file using proper git cascade.

    Cascade order:
    1. Working tree changes (unstaged): git diff -- <file>
    2. Staged changes: git diff --staged -- <file>
    3. Most recent commit: git log -1 -p -- <file>
    4. File content at HEAD: git show HEAD:<file>
    5. Direct file read (untracked new files)
    """
    empty = {"file": filepath, "diff_type": "none", "lines": [], "truncated": False}

    # 1. Unstaged working tree changes
    raw = _git_cmd(["git", "diff", "--", filepath], git_root)
    if raw:
        return _build_result(filepath, "uncommitted", raw, max_lines)

    # 2. Staged changes
    raw = _git_cmd(["git", "diff", "--staged", "--", filepath], git_root)
    if raw:
        return _build_result(filepath, "staged", raw, max_lines)

    # 3. Most recent commit that touched this file
    raw = _git_cmd(["git", "log", "-1", "-p", "--format=", "--", filepath], git_root)
    if raw:
        return _build_result(filepath, "last_commit", raw, max_lines)

    # 4. File content at HEAD (file exists but no diff history)
    content = _git_cmd(["git", "show", "HEAD:" + filepath], git_root)
    if content:
        return _content_as_new(filepath, content, max_lines)

    # 5. Direct read for untracked files
    full_path = git_root / filepath
    if full_path.is_file():
        try:
            content = full_path.read_text(errors="replace")
            if content:
                return _content_as_new(filepath, content, max_lines)
        except OSError:
            pass

    return empty


def _to_relative(name: str, git_root: Path) -> str:
    """Convert any path form to a safe repo-relative path.

    Returns an empty string if the path is invalid or would escape the repo.
    """
    # Strip whitespace, surrounding quotes, and any embedded NULs
    clean = name.replace("\x00", "").strip().strip("\"'`")
    if not clean:
        return ""

    # Absolute path: ensure it is under git_root and return a relative path
    try:
        p = Path(clean)
        if p.is_absolute():
            try:
                rel = p.resolve().relative_to(git_root.resolve())
            except (ValueError, OSError):
                # Path is outside the repo or cannot be resolved safely
                return ""
            return str(rel)
    except (ValueError, OSError):
        # Fall through to generic handling below
        pass

    # Relative or bare path: normalize and ensure it stays under git_root
    try:
        # Build a candidate absolute path and normalize it
        abs_candidate = (git_root / clean).resolve()
        try:
            rel = abs_candidate.relative_to(git_root.resolve())
        except ValueError:
            # Would escape the repo (e.g., contains '..')
            return ""
        return str(rel)
    except (ValueError, OSError):
        return ""


def _git_cmd(cmd: list[str], cwd: Path) -> str:
    """Run a git command and return stripped stdout, or empty string."""
    # Defensive guard: reject obviously invalid arguments (e.g., with NUL bytes)
    for part in cmd:
        if isinstance(part, str) and "\x00" in part:
            return ""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(cwd), timeout=10
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _build_result(filepath: str, diff_type: str, raw: str, max_lines: int) -> dict:
    """Parse raw diff output into structured result."""
    lines = _parse_diff_lines(raw)
    return {
        "file": filepath,
        "diff_type": diff_type,
        "lines": lines[:max_lines],
        "truncated": len(lines) > max_lines,
    }


def _content_as_new(filepath: str, content: str, max_lines: int) -> dict:
    """Wrap file content as a 'new file' diff (all additions)."""
    raw_lines = content.splitlines()
    lines = [{"text": "+" + ln, "type": "add"} for ln in raw_lines]
    return {
        "file": filepath,
        "diff_type": "new_file",
        "lines": lines[:max_lines],
        "truncated": len(lines) > max_lines,
    }


def _parse_diff_lines(raw: str) -> list[dict]:
    """Parse git diff/log output into structured line objects.

    Each line: {text: str, type: 'add'|'del'|'hunk'|'ctx'}
    Skips diff headers (diff, index, ---, +++ lines).
    """
    result: list[dict] = []
    for line in raw.splitlines():
        if line.startswith("diff ") or line.startswith("index "):
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("@@"):
            result.append({"text": line, "type": "hunk"})
        elif line.startswith("+"):
            result.append({"text": line, "type": "add"})
        elif line.startswith("-"):
            result.append({"text": line, "type": "del"})
        else:
            result.append({"text": line, "type": "ctx"})
    return result
