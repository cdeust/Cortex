"""Run the launcher on a Python the plugin supports — stdlib only, Python 3.9 safe.

Claude Code starts every hook and the MCP server with the first ``python3`` on
PATH. On a Mac with only the Command Line Tools that is Python 3.9.6, below
``requires-python`` (``>=3.11``, pyproject.toml), and the locked dependency
sets cannot install for it. Rather than ask the user to install a Python, the
launcher has the pinned uv (``launcher_uv``, bootstrapped with pip, which runs
on 3.9) install one pinned CPython into the plugin's data directory, then
re-executes itself on it. A Python that is already supported is used as is.

This module must import and run on Python 3.9: it is what gets the launcher
off it.

source: docs/adr/ADR-1104-zero-ops-plugin-install.md
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import launcher_layout as _layout
import launcher_uv as _uv
from launcher_sets import MANAGED_PYTHON

# source: pyproject.toml requires-python = ">=3.11"
SUPPORTED = (3, 11)


class InterpreterError(RuntimeError):
    """No supported Python could be provided; the message is uv's own error."""


class NotProvidedError(InterpreterError):
    """No supported Python is installed and this launch may not install one."""


def managed_dir(deps_dir: str) -> Path:
    """Where the pinned CPython lives: in plugin data, shared by every set."""
    return _layout.data_dir(deps_dir) / "python"


def _uv_python(deps_dir: str, *args: str) -> subprocess.CompletedProcess:
    env = _uv.environment()
    env["UV_PYTHON_INSTALL_DIR"] = str(managed_dir(deps_dir))
    return subprocess.run(
        [_uv.locate(deps_dir), "python", *args, MANAGED_PYTHON, "--managed-python"],
        capture_output=True,
        text=True,
        encoding="utf-8",  # uv writes UTF-8 (a Rust program)
        env=env,
    )


def _record(deps_dir: str) -> Path:
    """Where ``provide`` writes the interpreter path, so a hook need not ask uv."""
    return managed_dir(deps_dir) / "interpreter"


def installed(deps_dir: str) -> str | None:
    """The pinned CPython ``provide`` installed, read from its record: no
    subprocess, so a hook on Python 3.9 pays one exec, not a uv call
    (measured 0.26 s with ``uv python find`` vs 0.10 s direct, 2026-10-14)."""
    try:
        path = _record(deps_dir).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return path if path and os.access(path, os.X_OK) else None


def provide(deps_dir: str) -> str:
    """Install the pinned CPython if absent; return its interpreter path.

    Raises ``InterpreterError`` with uv's message when it cannot.
    """
    found = _uv_python(deps_dir, "find")
    if found.returncode:
        print(
            f"[cortex-launcher] Python {sys.version.split()[0]} is older than "
            f"{SUPPORTED[0]}.{SUPPORTED[1]}; installing Python {MANAGED_PYTHON} "
            f"into {managed_dir(deps_dir)}",
            file=sys.stderr,
        )
        done = _uv_python(deps_dir, "install")
        if done.returncode:
            raise InterpreterError((done.stderr or done.stdout).strip())
        found = _uv_python(deps_dir, "find")
        if found.returncode:
            raise InterpreterError((found.stderr or found.stdout).strip())
    path = found.stdout.strip()
    _record(deps_dir).write_text(path, encoding="utf-8")
    return path


def supported() -> bool:
    return sys.version_info[:2] >= SUPPORTED


def ensure_supported(deps_dir: str, launcher: str, may_provide: bool = True) -> None:
    """Return on a supported Python; otherwise re-exec the launcher on one.

    Postcondition: returns only when ``sys.version_info >= SUPPORTED``. Exits
    1 with the real cause when no supported Python can be provided. With
    ``may_provide`` False (a hook: its host time budget does not fit a
    download) an installed Python is still used, and a missing one raises
    ``NotProvidedError`` before anything is downloaded.
    """
    if supported():
        return
    python = installed(deps_dir)
    if python is None and not may_provide:
        raise NotProvidedError(
            f"Python {sys.version.split()[0]} is older than "
            f"{SUPPORTED[0]}.{SUPPORTED[1]} and Python {MANAGED_PYTHON} is "
            "not installed yet"
        )
    try:
        python = python or provide(deps_dir)
    except (OSError, _uv.UvUnavailableError, InterpreterError) as exc:
        print(
            f"[cortex-launcher] cannot run on Python {sys.version.split()[0]} "
            f"(Cortex needs >= {SUPPORTED[0]}.{SUPPORTED[1]}) and could not "
            f"install Python {MANAGED_PYTHON}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    sys.stdout.flush()
    sys.stderr.flush()
    argv = [python, launcher, *sys.argv[1:]]
    if sys.platform == "win32":  # execv there spawns and returns: stdio would split
        sys.exit(subprocess.call(argv))
    os.execv(python, argv)
