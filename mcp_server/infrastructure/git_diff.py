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

    # Security: validate the relative path stays within the repo before any use
    if not _path_within_root(rel, git_root):
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

    # File exists on disk but untracked — pre-sanitize then validate
    safe_rel = _sanitize_path(rel)
    if safe_rel:
        full = (git_root / safe_rel).resolve()
        if full.is_file() and str(full).startswith(str(git_root.resolve()) + os.sep):
            return safe_rel

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

    # Security: validate filepath stays within repo before any use
    if not _path_within_root(filepath, git_root):
        return empty

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
    # Validate: filepath must not contain null bytes or shell metacharacters
    safe_ref = "HEAD:" + filepath
    content = _git_cmd(["git", "show", safe_ref], git_root)
    if content:
        return _content_as_new(filepath, content, max_lines)

    # 5. Direct read for untracked files — pre-sanitized path
    safe_fp = _sanitize_path(filepath)
    if not safe_fp:
        return empty
    resolved_root = git_root.resolve()
    full_path = (git_root / safe_fp).resolve()
    if full_path.is_file() and str(full_path).startswith(str(resolved_root) + os.sep):
        try:
            content = full_path.read_text(errors="replace")
            if content:
                return _content_as_new(filepath, content, max_lines)
        except OSError:
            pass

    return empty


def _sanitize_path(rel_path: str) -> str | None:
    """Sanitize a relative path string BEFORE any filesystem operations.

    Returns the sanitized path or None if it's unsafe.
    This pre-validation ensures CodeQL sees the path as safe
    before it flows into resolve() or any filesystem call.
    """
    if not rel_path or not isinstance(rel_path, str):
        return None
    # Reject null bytes
    if "\x00" in rel_path:
        return None
    # Reject absolute paths
    if os.path.isabs(rel_path):
        return None
    # Reject path traversal components
    parts = rel_path.replace("\\", "/").split("/")
    if ".." in parts:
        return None
    # Reject hidden files/dirs (dotfiles)
    if any(p.startswith(".") and p not in (".", "") for p in parts):
        return None
    # Reject shell metacharacters
    if any(c in rel_path for c in (";", "&", "|", "$", "`", "\n", "\r")):
        return None
    return rel_path


def _path_within_root(rel_path: str, git_root: Path) -> bool:
    """Validate that a relative path is safe and resolves within the git root."""
    safe = _sanitize_path(rel_path)
    if safe is None:
        return False
    try:
        resolved_root = git_root.resolve()
        resolved_path = (git_root / safe).resolve()
        return (
            str(resolved_path).startswith(str(resolved_root) + os.sep)
            or resolved_path == resolved_root
        )
    except (ValueError, OSError):
        return False


def _to_relative(name: str, git_root: Path) -> str:
    """Convert any path form to repo-relative."""
    clean = name.strip().strip("\"'`")
    try:
        p = Path(clean)
        if p.is_absolute():
            return str(p.relative_to(git_root))
    except (ValueError, OSError):
        pass
    # Try os.path.relpath as fallback for tricky paths
    if os.path.isabs(clean):
        try:
            return os.path.relpath(clean, str(git_root))
        except ValueError:
            pass
    return clean


def _git_cmd(cmd: list[str], cwd: Path) -> str:
    """Run a git command and return stripped stdout, or empty string.

    Security: cmd must be a list (no shell=True). All arguments are passed
    as separate list elements to prevent shell injection. Arguments are
    validated to reject null bytes and shell metacharacters.
    """
    try:
        # Validate: only allow git commands, never shell=True
        if not cmd or cmd[0] != "git":
            return ""
        # Reject arguments containing null bytes (argument injection)
        for arg in cmd:
            if "\x00" in arg:
                return ""
        # Validate: only known git subcommands are allowed
        _allowed_subcommands = {
            "rev-parse",
            "ls-files",
            "diff",
            "log",
            "show",
        }
        if len(cmd) < 2 or cmd[1] not in _allowed_subcommands:
            return ""
        # Sanitize all arguments: reject shell metacharacters
        for arg in cmd[2:]:
            if any(c in arg for c in (";", "&", "|", "$", "`", "\n", "\r")):
                return ""
        # Build a clean command list with only validated arguments
        clean_cmd = ["git", cmd[1]] + [str(a) for a in cmd[2:]]
        result = subprocess.run(  # noqa: S603
            clean_cmd,
            capture_output=True,
            text=True,
            shell=False,
            cwd=str(cwd),
            timeout=10,
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
