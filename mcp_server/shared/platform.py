"""Cross-platform primitives. shared/ → Python stdlib only.

Centralizes the three portability hazards that silently broke Cortex on
Windows (each previously open-coded at several call sites):

  1. ``python3`` on the Windows PATH resolves to the Microsoft Store stub —
     it does not run an interpreter, it prints a message and exits 9009.
     Shelling out to a Python interpreter by name is therefore unsafe.
  2. ``Path.home()`` and ``Path.expanduser()`` consult USERPROFILE /
     HOMEDRIVE+HOMEPATH on Windows and silently ignore ``$HOME``. Tests that
     ``monkeypatch.setenv("HOME", ...)`` and admin setups that point HOME at
     a network share both observe the wrong directory as a result.
  3. ``str(Path(...))`` and ``os.path.relpath`` emit backslash separators on
     Windows, which fail regex matches and string comparisons authored for
     forward slashes.

These are one-liners, but they were duplicated and each duplication was a
fresh place to forget the Windows branch. Three+ call sites each → extract
(coding-standards §3.3).

source: RAPPORT_INSTALLATION_CORTEX_WINDOWS.md §5.1, §5.2, §5.3
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Union

IS_WINDOWS = sys.platform == "win32"


def home_dir() -> Path:
    """Home directory, honoring an explicit ``$HOME`` override on every OS.

    ``Path.home()`` ignores ``$HOME`` on Windows. We prefer ``$HOME`` when it
    is set so test fixtures and admin overrides behave identically across
    platforms, and fall back to the OS default otherwise.
    """
    override = os.environ.get("HOME")
    return Path(override) if override else Path.home()


def python_executable() -> str:
    """Absolute path to the interpreter currently executing.

    Always use this instead of ``shutil.which("python3")`` /
    ``shutil.which("python")`` when spawning a Python subprocess: on Windows
    those resolve to the Microsoft Store stub before the real interpreter.
    ``sys.executable`` is, by definition, the interpreter running this code.
    """
    return sys.executable


def to_posix(path: Union[str, os.PathLike]) -> str:
    """Render a path with forward slashes regardless of host OS separator.

    Use whenever a path is stringified for storage, comparison, or regex
    matching. On POSIX this is a no-op; on Windows it rewrites ``\\`` → ``/``.
    """
    text = os.fspath(path)
    return text.replace(os.sep, "/") if os.sep != "/" else text
