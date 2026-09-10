"""Cross-platform primitives. shared/ → Python stdlib only.

source: ADR-0660"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Union

IS_WINDOWS = sys.platform == "win32"


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
