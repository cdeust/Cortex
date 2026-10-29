"""Git plumbing for the craftsmanship gate: listing the tracked files the
gate measures. No ref is read: the baseline is the file committed in the
same tree as the code measured against it.

source: ADR-0723"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


def _run_git(repo_root: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout


def all_tracked_python_files(repo_root: Path) -> list[str]:
    """Every git-tracked ``.py`` file — the scope for ``--write-baseline``."""
    output = _run_git(repo_root, ["ls-files", "--", "*.py"]) or ""
    return sorted(line for line in output.splitlines() if line)
