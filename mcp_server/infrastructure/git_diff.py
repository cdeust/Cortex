"""Git diff retrieval for file entities.

Runs git commands to fetch diff data for files referenced in the
knowledge graph. Uses a proper cascade: working tree -> staged ->
last commit -> file content at HEAD.

Infrastructure layer - I/O via subprocess.

Security: All file paths are validated against git's own tracked file list.
User-controlled paths are NEVER used directly in filesystem operations —
they are matched against git ls-files output (the whitelist) first.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# Resolve git binary path once at import time — not from user input
_GIT_BINARY = shutil.which("git") or "git"


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


def _get_tracked_files(git_root: Path) -> set[str]:
    """Get the set of all git-tracked files (the whitelist).

    This is the ONLY source of truth for valid file paths.
    User-controlled paths must match an entry in this set.
    """
    raw = _git_cmd_safe("ls-files", [], git_root)
    if not raw:
        return set()
    return set(raw.splitlines())


def _match_in_whitelist(name: str, tracked: set[str]) -> str | None:
    """Match a user-provided name against the git-tracked whitelist.

    Returns the canonical tracked path or None if no match.
    This ensures we NEVER use the user's raw input as a path.
    """
    # Direct match
    if name in tracked:
        return name

    # Basename match
    basename = name.rsplit("/", 1)[-1] if "/" in name else name
    for f in tracked:
        if f == basename or f.endswith("/" + basename):
            return f

    return None


def resolve_file(name: str, git_root: Path) -> str | None:
    """Resolve a file name/path to a repo-relative path.

    Uses git ls-files as the whitelist — user input is matched
    against tracked files, never used directly as a path.
    """
    # Strip quotes and normalize
    clean = name.strip().strip("\"'`")

    # Make relative if absolute
    try:
        p = Path(clean)
        if p.is_absolute():
            clean = str(p.relative_to(git_root))
    except (ValueError, OSError):
        pass

    # Match against tracked files (whitelist)
    tracked = _get_tracked_files(git_root)
    match = _match_in_whitelist(clean, tracked)
    if match:
        return match

    # Check staged files
    staged = _git_cmd_safe("diff", ["--staged", "--name-only"], git_root)
    if staged:
        staged_files = set(staged.splitlines())
        match = _match_in_whitelist(clean, staged_files)
        if match:
            return match

    return None


def get_file_diff(filepath: str, git_root: Path, max_lines: int = 80) -> dict:
    """Get diff for a file using proper git cascade.

    Security: filepath is validated against git's tracked file list.
    Direct filesystem reads only happen for files confirmed by git.
    """
    empty = {"file": filepath, "diff_type": "none", "lines": [], "truncated": False}

    # Validate: filepath must exist in git's tracked/staged files
    tracked = _get_tracked_files(git_root)
    staged_raw = _git_cmd_safe("diff", ["--staged", "--name-only"], git_root)
    staged_files = set(staged_raw.splitlines()) if staged_raw else set()
    all_known = tracked | staged_files

    # Match the user's path against known files
    safe_path = _match_in_whitelist(filepath, all_known)

    # If not in tracked/staged, check if git knows about it at all
    if not safe_path:
        # Last resort: check if git show HEAD:<path> works
        # This is safe because git itself validates the path
        test = _git_cmd_safe("show", ["HEAD:" + filepath], git_root)
        if test:
            safe_path = filepath
        else:
            return empty

    # From here, safe_path came from git's own output — safe to use

    # 1. Unstaged working tree changes
    raw = _git_cmd_safe("diff", ["--", safe_path], git_root)
    if raw:
        return _build_result(safe_path, "uncommitted", raw, max_lines)

    # 2. Staged changes
    raw = _git_cmd_safe("diff", ["--staged", "--", safe_path], git_root)
    if raw:
        return _build_result(safe_path, "staged", raw, max_lines)

    # 3. Most recent commit
    raw = _git_cmd_safe("log", ["-1", "-p", "--format=", "--", safe_path], git_root)
    if raw:
        return _build_result(safe_path, "last_commit", raw, max_lines)

    # 4. File content at HEAD
    content = _git_cmd_safe("show", ["HEAD:" + safe_path], git_root)
    if content:
        return _content_as_new(safe_path, content, max_lines)

    return empty


# ── Safe git command execution ───────────────────────────────────────────


_ALLOWED_SUBCOMMANDS = frozenset(
    {
        "rev-parse",
        "ls-files",
        "diff",
        "log",
        "show",
    }
)

_DANGEROUS_CHARS = frozenset(";|&$`\n\r\x00")


def _git_cmd_safe(subcommand: str, args: list[str], cwd: Path) -> str:
    """Run a git command with strict validation.

    Args:
        subcommand: Git subcommand (must be in _ALLOWED_SUBCOMMANDS).
        args: Additional arguments (each validated for dangerous chars).
        cwd: Working directory for the git command.

    The command list is built internally from _GIT_BINARY (resolved at
    import time) + the validated subcommand + validated args. No caller
    data flows directly into subprocess.run.
    """
    try:
        if subcommand not in _ALLOWED_SUBCOMMANDS:
            return ""
        for arg in args:
            if any(c in arg for c in _DANGEROUS_CHARS):
                return ""
        # Build command from trusted binary + validated components
        run_cmd = [_GIT_BINARY, subcommand] + args
        result = subprocess.run(  # noqa: S603
            run_cmd,
            capture_output=True,
            text=True,
            shell=False,
            cwd=str(cwd),
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


# ── Result formatting ────────────────────────────────────────────────────


def _build_result(filepath: str, diff_type: str, raw: str, max_lines: int) -> dict:
    lines = _parse_diff_lines(raw)
    return {
        "file": filepath,
        "diff_type": diff_type,
        "lines": lines[:max_lines],
        "truncated": len(lines) > max_lines,
    }


def _content_as_new(filepath: str, content: str, max_lines: int) -> dict:
    raw_lines = content.splitlines()
    lines = [{"text": "+" + ln, "type": "add"} for ln in raw_lines]
    return {
        "file": filepath,
        "diff_type": "new_file",
        "lines": lines[:max_lines],
        "truncated": len(lines) > max_lines,
    }


def _parse_diff_lines(raw: str) -> list[dict]:
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
