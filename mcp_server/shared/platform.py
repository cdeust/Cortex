"""Cross-platform primitives. shared/ → Python stdlib only.

source: ADR-0660"""

from __future__ import annotations

import os
import sys
from pathlib import Path, PureWindowsPath
from typing import Optional, Union

IS_WINDOWS = sys.platform == "win32"

# Directories that hold the WSL launcher stubs, not a usable bash.
# source: issue #689 (windows-latest run 38008915302); ADR-1101
_WSL_STUB_DIRS = frozenset({"system32", "sysnative", "syswow64", "windowsapps"})
# Git for Windows keeps git.exe in cmd\, bin\ or mingw64\bin\ and bash.exe in
# bin\: up to two parents separate them.
# source: ADR-1101 (Git for Windows install layout).
_GIT_ROOT_DEPTH = 3
_NO_BASH = (
    "No usable bash found. Cortex on native Windows needs Git for Windows "
    "(https://git-scm.com/download/win); running Cortex inside WSL is the "
    "recommended setup on Windows. WSL launcher stubs skipped: {stubs}"
)


class BashNotFoundError(RuntimeError):
    """No usable bash: the caller fails instead of skipping. source: ADR-1101"""


def home_dir() -> Path:
    """Home directory, honoring an explicit ``$HOME`` override on every OS.

    source: ADR-0660"""
    override = os.environ.get("HOME")
    return Path(override) if override else Path.home()


def cache_dir() -> Path:
    """Base cache directory, honoring ``$XDG_CACHE_HOME`` when set.

    source: ADR-0660"""
    override = os.environ.get("XDG_CACHE_HOME")
    return Path(override) if override else home_dir() / ".cache"


def python_executable() -> str:
    """Absolute path to the interpreter currently executing.

    source: ADR-0660"""
    return sys.executable


def to_posix(path: Union[str, os.PathLike]) -> str:
    """Render a path with forward slashes regardless of host OS separator.

    Use whenever a path is stringified for storage, comparison, or regex
    matching. On POSIX this is a no-op; on Windows it rewrites ``\\`` → ``/``.
    """
    text = os.fspath(path)
    return text.replace(os.sep, "/") if os.sep != "/" else text


def _is_wsl_stub(candidate: str) -> bool:
    parents = PureWindowsPath(candidate).parts[:-1]
    return any(part.lower() in _WSL_STUB_DIRS for part in parents)


def _on_path(name: str, path_env: str, windows: bool) -> list[str]:
    found = []
    for directory in filter(None, path_env.split(os.pathsep)):
        candidate = os.path.join(directory, name)
        # Windows has no execute bit: an .exe that exists is runnable.
        runnable = windows or os.access(candidate, os.X_OK)
        if os.path.isfile(candidate) and runnable:
            found.append(os.path.abspath(candidate))
    return found


def _bash_beside_git(path_env: str) -> Optional[str]:
    for git in _on_path("git.exe", path_env, True):
        for root in Path(git).parents[:_GIT_ROOT_DEPTH]:
            candidate = root / "bin" / "bash.exe"
            if candidate.is_file() and not _is_wsl_stub(str(candidate)):
                return str(candidate)
    return None


def resolve_bash(*, path_env: Optional[str] = None, windows: bool = IS_WINDOWS) -> str:
    """Absolute path of a usable bash; raises BashNotFoundError, never skips.

    Callers put the result in argv[0]: a bare ``bash`` on Windows resolves to
    the System32 WSL stub before PATH.

    source: ADR-1101 (issue #689)"""
    path_env = os.environ.get("PATH", "") if path_env is None else path_env
    candidates = _on_path("bash.exe" if windows else "bash", path_env, windows)
    stubs = [c for c in candidates if windows and _is_wsl_stub(c)]
    usable = [c for c in candidates if c not in stubs]
    if usable:
        return usable[0]
    beside_git = _bash_beside_git(path_env) if windows else None
    if beside_git:
        return beside_git
    raise BashNotFoundError(_NO_BASH.format(stubs=", ".join(stubs) or "none"))
