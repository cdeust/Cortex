#!/usr/bin/env python3
"""Cross-platform launcher for Cortex MCP server and hooks.

Sets up PYTHONPATH, DATABASE_URL, and working directory, then runs the
target module. Works on Windows (cmd.exe), macOS, and Linux — no bash
or shell-specific syntax required.

Usage:
    python3 scripts/launcher.py <module> [--install-deps]

Examples:
    python3 scripts/launcher.py mcp_server                       # MCP server
    python3 scripts/launcher.py mcp_server.hooks.session_start   # Hook
    python3 scripts/launcher.py mcp_server.hooks.auto_recall     # Hook
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _resolve_paths() -> tuple[str, str]:
    """Resolve plugin root and deps directory."""
    # CLAUDE_PLUGIN_ROOT is set by Claude Code for plugins
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if not plugin_root or not Path(plugin_root).is_dir():
        # Fall back to this script's parent's parent
        plugin_root = str(Path(__file__).resolve().parent.parent)

    # CLAUDE_PLUGIN_DATA is set by Claude Code — persistent across updates
    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA", "")
    if plugin_data:
        deps_dir = os.path.join(plugin_data, "deps")
    else:
        deps_dir = os.path.join(plugin_root, "deps")

    return plugin_root, deps_dir


def _ensure_deps(deps_dir: str) -> None:
    """Install minimal dependencies if missing.

    The plugin's MCP server, hooks, and handlers all transitively import
    the full base runtime (fastmcp, pydantic, pydantic-settings, numpy)
    plus the postgres trio (psycopg, psycopg_pool, pgvector). When the
    plugin runs against system python (the marketplace install path),
    none of these are guaranteed to be present, so any missing one
    causes an ImportError before the MCP server registers tools or a
    hook can read its payload. Install whatever's missing in a single
    pip call so partial states (e.g., pydantic present but fastmcp
    absent after a python upgrade) self-heal.
    """
    os.makedirs(deps_dir, exist_ok=True)
    missing: list[str] = []
    # Base runtime — required by every entry point.
    try:
        import fastmcp  # noqa: F401
    except ImportError:
        missing.append("fastmcp>=2.0.0")
    try:
        import pydantic  # noqa: F401
    except ImportError:
        missing.append("pydantic>=2.0.0")
    try:
        import pydantic_settings  # noqa: F401
    except ImportError:
        missing.append("pydantic-settings>=2.0.0")
    try:
        import numpy  # noqa: F401
    except ImportError:
        missing.append("numpy>=1.24.0")
    # Postgres extras — required because pg_store hard-imports at module load.
    try:
        import psycopg  # noqa: F401
    except ImportError:
        missing.append("psycopg[binary]>=3.1")
    try:
        import psycopg_pool  # noqa: F401
    except ImportError:
        missing.append("psycopg_pool>=3.2")
    try:
        import pgvector  # noqa: F401
    except ImportError:
        missing.append("pgvector>=0.3")
    if not missing:
        return
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-q",
            "--target",
            deps_dir,
            *missing,
        ],
        capture_output=True,
    )


def _ensure_all_deps(deps_dir: str) -> None:
    """Install all dependencies including ML packages."""
    _ensure_deps(deps_dir)
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-q",
                "--target",
                deps_dir,
                "sentence-transformers>=2.2.0",
                "flashrank>=0.2.0",
            ],
            capture_output=True,
        )


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python3 scripts/launcher.py <module> [--install-deps]",
            file=sys.stderr,
        )
        sys.exit(1)

    module = sys.argv[1]
    install_deps = "--install-deps" in sys.argv

    plugin_root, deps_dir = _resolve_paths()

    # Set up environment
    path_sep = ";" if sys.platform == "win32" else ":"
    current_pypath = os.environ.get("PYTHONPATH", "")
    new_paths = [plugin_root, deps_dir]
    if current_pypath:
        new_paths.append(current_pypath)
    os.environ["PYTHONPATH"] = path_sep.join(new_paths)

    # Ensure PYTHONPATH entries are in sys.path for this process
    for p in [plugin_root, deps_dir]:
        if p not in sys.path:
            sys.path.insert(0, p)

    # Set DATABASE_URL default if not set
    if "DATABASE_URL" not in os.environ:
        os.environ["DATABASE_URL"] = "postgresql://localhost:5432/cortex"

    # Install deps. The base-deps check is a tight no-op when everything
    # is already present, so we always run it — every entry point (server,
    # hooks, doctor) imports the same base stack and crashes the same way
    # if anything is missing. SessionStart additionally needs the heavy
    # ML stack (sentence-transformers, flashrank).
    if module == "mcp_server.hooks.session_start" or install_deps:
        _ensure_all_deps(deps_dir)
    else:
        _ensure_deps(deps_dir)

    # Change to plugin root
    os.chdir(plugin_root)

    # Run the target module
    sys.argv = [module] + [a for a in sys.argv[2:] if a != "--install-deps"]
    try:
        from runpy import run_module

        run_module(module, run_name="__main__", alter_sys=True)
    except SystemExit:
        raise
    except Exception as e:
        print(f"[cortex-launcher] Failed to run {module}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
