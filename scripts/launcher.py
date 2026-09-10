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
import sys
from pathlib import Path

# source: ADR-0742
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import launcher_deps  # noqa: E402

_MIN_ARGC = 2  # source: ADR-0742


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


def _reconfigure_streams_utf8() -> None:
    """Force UTF-8 encoding on stdout/stderr, replacing unencodable chars.

        Precondition: none — safe to call unconditionally, before argv parsing.
        Postcondition: sys.stdout and sys.stderr each either (a) have
        encoding="utf-8" and errors="replace", or (b) are left untouched if
        reconfigure() is unavailable/fails — never raises.

        Claude Code consumes hook stdout as UTF-8 regardless of the host
        locale, so forcing utf-8 here is what the consumer already expects;
        errors="replace" is a defense-in-depth fallback for any character
        not exercised by the reporter's A/B.

        reconfigure() is a TextIOWrapper method (Python 3.7+); it can raise
        if the stream isn't a TextIOWrapper (e.g. already replaced by a
        test harness) — caught per-stream so one stream's failure can't
        skip the other's.

    source: ADR-0742"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main() -> None:
    # source: ADR-0742
    _reconfigure_streams_utf8()

    if len(sys.argv) < _MIN_ARGC:
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

    if (
        module == "mcp_server.hooks.post_tool_capture"
        and not install_deps
        and os.environ.get("CORTEX_CAPTURE_MODE", "full") != "full"
    ):
        from launcher_capture import skip_capture  # noqa: PLC0415 — only non-full capture needs the stdlib preflight; plugin path is now established

        if skip_capture():
            return

    # Persisted-backend resolution: translate the installer's
    # ~/.claude/methodology/backend.json marker (SQLite zero-config
    # default vs --postgres opt-in) into CORTEX_MEMORY_STORE_BACKEND.
    # backend_marker is stdlib-only (json/pathlib), so this import is
    # safe before ensure_deps has run. Best-effort: a broken marker or
    # import must never block a hook or the server from starting — the
    # engine's "auto" default then applies, exactly as before the
    # marker existed.
    try:
        from mcp_server.infrastructure.backend_marker import (  # noqa: PLC0415 — plugin root joins sys.path inside main() a few lines above; this module is only resolvable after that
            apply_backend_resolution,
        )

        apply_backend_resolution(os.environ)
    except Exception as exc:  # noqa: BLE001 — launch must survive any marker failure
        print(f"[cortex-launcher] backend resolution skipped: {exc}", file=sys.stderr)

    # Set DATABASE_URL default if not set — PostgreSQL paths only. On
    # the SQLite backend the URL is unused, and injecting a PG default
    # would make every hook attempt (and log) a doomed PG connection.
    if (
        "DATABASE_URL" not in os.environ
        and os.environ.get("CORTEX_MEMORY_STORE_BACKEND", "") != "sqlite"
    ):
        os.environ["DATABASE_URL"] = "postgresql://localhost:5432/cortex"

    # source: ADR-0742
    if module == "mcp_server.hooks.session_start" or install_deps:
        launcher_deps.ensure_all_deps(deps_dir)
    else:
        launcher_deps.ensure_deps(deps_dir)

    # Change to plugin root
    os.chdir(plugin_root)

    # Run the target module
    sys.argv = [module] + [a for a in sys.argv[2:] if a != "--install-deps"]
    try:
        from runpy import run_module  # noqa: PLC0415 — runpy is imported at dispatch time inside the launch boundary try so a corrupt stdlib install is reported, not a crash

        run_module(module, run_name="__main__", alter_sys=True)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — failure is reported to stderr; execution degrades, never crashes
        print(f"[cortex-launcher] Failed to run {module}: {e}", file=sys.stderr)
        sys.exit(1)


def entrypoint() -> None:
    """Keep cleanup imports and registry I/O out of per-tool hook launches."""
    arguments = sys.argv[1:]
    if arguments and arguments[0].partition("=")[0] in {
        "--cleanup-deps",
        "--dry-run",
        "--apply",
        "--plugin-id",
    }:
        from launcher_cleanup import cli  # noqa: PLC0415 — explicit maintenance only

        _reconfigure_streams_utf8()
        sys.exit(cli(arguments))
    if (
        arguments
        and arguments[0] == "mcp_server"
        and os.environ.get("CORTEX_CLAUDE_DIR")
    ):
        from launcher_cleanup import audit_startup  # noqa: PLC0415 — server startup only

        audit_startup()
    main()


if __name__ == "__main__":
    entrypoint()
