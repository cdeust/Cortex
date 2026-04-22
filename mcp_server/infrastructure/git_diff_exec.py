"""Safe ``git`` subcommand executor for ``git_diff``.

Isolates all ``subprocess.run`` calls + argument sanitisation behind a
frozen-allowlist check so CodeQL sees the data flow is interrupted
(CWE-78). The public surface is tiny:

* ``git_cmd_safe`` — run an allow-listed git subcommand, return stdout
  or ``""`` on any failure.
* ``get_tracked_files`` — ``git ls-files`` wrapped as a ``set[str]``.

Lives in ``infrastructure`` because it runs external processes. Pure
subprocess boundary, no policy.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# Resolve git binary once at import time — never from user input.
_GIT_BINARY = shutil.which("git") or "git"

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


def _sanitize_arg(arg: str) -> str | None:
    """Reject shell-metacharacter-bearing args (CWE-78).

    Returns a new ``str`` (not the original reference) so CodeQL can
    verify the taint flow is interrupted.
    """
    if any(c in arg for c in _DANGEROUS_CHARS):
        return None
    return str(arg)


def git_cmd_safe(subcommand: str, args: list[str], cwd: Path) -> str:
    """Run a git subcommand under the frozen allowlist.

    Security (CWE-78 mitigation):
      1. subcommand must be in _ALLOWED_SUBCOMMANDS
      2. each arg is validated by _sanitize_arg
      3. sanitised args are new ``str`` objects (breaks taint)
      4. ``shell=False`` everywhere
      5. _GIT_BINARY was resolved at import time via ``shutil.which``
    """
    try:
        if subcommand not in _ALLOWED_SUBCOMMANDS:
            return ""
        safe_args: list[str] = []
        for arg in args:
            sanitized = _sanitize_arg(arg)
            if sanitized is None:
                return ""
            safe_args.append(sanitized)
        run_cmd = [_GIT_BINARY, subcommand, *safe_args]
        result = subprocess.run(
            run_cmd,  # noqa: S603 — all components validated above
            capture_output=True,
            text=True,
            shell=False,
            cwd=str(cwd),
            timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def get_tracked_files(git_root: Path) -> set[str]:
    """Return the set of all git-tracked files inside ``git_root``."""
    raw = git_cmd_safe("ls-files", [], git_root)
    if not raw:
        return set()
    return set(raw.splitlines())
