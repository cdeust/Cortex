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

import importlib
import os
import sys
from pathlib import Path

# source: ADR-0742
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import launcher_backend  # noqa: E402
import launcher_deps  # noqa: E402
import launcher_mcp_bootstrap  # noqa: E402
import launcher_ml  # noqa: E402
import launcher_python  # noqa: E402
import launcher_site  # noqa: E402

_MIN_ARGC = 2  # source: ADR-0742
_LAUNCHER = str(
    Path(__file__).resolve()
)  # source: ADR-1104 (re-exec and background job target)


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


def _use_utf8_output(plugin_root: str) -> None:
    """Set stdout/stderr to UTF-8 through the one shared hook output path.

    Precondition: ``plugin_root`` holds ``mcp_server`` (``_resolve_paths``).
    Postcondition: ``mcp_server.hooks.output_streams.use_utf8_output`` has run
    (stdout strict UTF-8, stderr UTF-8 with backslashreplace); a stream that
    cannot be reconfigured raises ``HookOutputStreamError``, it is not skipped.
    The module is stdlib-only and ``mcp_server/__init__`` and
    ``mcp_server/hooks/__init__`` import nothing, so this is safe before
    ``ensure_deps``.

    source: ADR-1098 (supersedes the output half of ADR-0742; its choke
    point stays), issue #688.
    """
    if plugin_root not in sys.path:
        sys.path.insert(0, plugin_root)
    from mcp_server.hooks.output_streams import use_utf8_output  # noqa: PLC0415 — resolvable only once plugin_root is on sys.path

    use_utf8_output()


def _set_import_paths(plugin_root: str, deps_dir: str) -> None:
    """PYTHONPATH for children, sys.path for this process; deps isolated."""
    path_sep = ";" if sys.platform == "win32" else ":"
    current_pypath = os.environ.get("PYTHONPATH", "")
    new_paths = [plugin_root, deps_dir]
    if current_pypath:
        new_paths.append(current_pypath)
    os.environ["PYTHONPATH"] = path_sep.join(new_paths)
    if plugin_root not in sys.path:
        sys.path.insert(0, plugin_root)
    # deps_dir joins sys.path here and nowhere else: being merely first on
    # it is not isolation (pywin32.pth, unvendored torchvision).
    # source: issue #621
    launcher_site.isolate_deps(deps_dir)


def _apply_backend() -> None:
    """One storage backend for the server and every hook.

    The host passes the user's ``database_url`` to the MCP server as
    ``DATABASE_URL`` and to hooks only as ``CLAUDE_PLUGIN_OPTION_DATABASE_URL``;
    both mean the same setting. Then the shared precedence (backend_marker)
    with the plugin's default. A HOME nothing decides gets its marker once
    (launcher_backend): SQLite when fresh, the earlier local PostgreSQL when
    it still answers. PostgreSQL's local URL default applies only when a
    marker chose it.

    source: ADR-0505
    source: ADR-1104
    """
    option = os.environ.get("CLAUDE_PLUGIN_OPTION_DATABASE_URL", "").strip()
    if option and not os.environ.get("DATABASE_URL", "").strip():
        os.environ["DATABASE_URL"] = option
    from mcp_server.infrastructure.backend_marker import (  # noqa: PLC0415 — resolvable once plugin_root is on sys.path
        BackendMarkerError,
        apply_backend_resolution,
        environment_decides,
        read_backend_marker,
    )

    try:
        if not environment_decides(os.environ) and read_backend_marker() is None:
            launcher_backend.persist_first_decision()
        apply_backend_resolution(os.environ, default="sqlite")
    except (BackendMarkerError, OSError) as exc:
        print(f"[cortex-launcher] Cortex not ready: {exc}", file=sys.stderr)
        sys.exit(1)
    if (
        "DATABASE_URL" not in os.environ
        and os.environ.get("CORTEX_MEMORY_STORE_BACKEND", "") == "postgresql"
    ):
        os.environ["DATABASE_URL"] = "postgresql://localhost:5432/cortex"


def _ensure_runtime(module: str, install_deps: bool, deps_dir: str) -> None:
    """The dependency sets ``module`` needs, then semantic search in background.

    Only the semantic-search job installs the ML set (launcher_ml); the
    SessionStart launch starts that job and tells the hook where it stands.
    source: ADR-0742
    source: ADR-1104
    """
    if install_deps:
        launcher_deps.ensure_all_deps(deps_dir)
    else:
        launcher_deps.ensure_deps(deps_dir)
    # The import system cached deps_dir as it was before this install
    # (source: ADR-1104).
    importlib.invalidate_caches()
    # The locked set just installed can add a .pth (~0.5 ms). source: issue #621
    launcher_site.isolate_deps(deps_dir)
    if module == "mcp_server.hooks.session_start":
        semantic, detail = launcher_ml.start(deps_dir, _LAUNCHER)
        os.environ["CORTEX_SEMANTIC_SEARCH"] = semantic
        os.environ["CORTEX_SEMANTIC_SEARCH_DETAIL"] = detail


def _run(module: str, plugin_root: str) -> None:
    """Wire the composition root, then run ``module`` as ``__main__``."""
    os.chdir(plugin_root)
    # source: issue #560 -- the one composition root shared by the server
    # and every hook (ADR-0742).
    from mcp_server.hooks.wiring import wire_composition_root  # noqa: PLC0415

    wire_composition_root()
    sys.argv = [module] + [a for a in sys.argv[2:] if a != "--install-deps"]
    try:
        from runpy import run_module  # noqa: PLC0415 — inside the launch boundary so a corrupt stdlib install is reported, not a crash

        run_module(module, run_name="__main__", alter_sys=True)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — failure is reported to stderr with its cause; the exit code carries it
        print(f"[cortex-launcher] Failed to run {module}: {e}", file=sys.stderr)
        sys.exit(1)


def _needs_stand_in(module: str, deps_dir: str) -> bool:
    """The MCP server's runtime is not installed: the host cannot wait for it.

    source: ADR-1104
    """
    if module != "mcp_server" or os.environ.get(launcher_mcp_bootstrap.DIRECT_ENV):
        return False
    if not launcher_python.supported():
        return launcher_python.installed(deps_dir) is None
    return not launcher_deps.set_ready(deps_dir, "base")


def main() -> None:
    # source: ADR-1098 (supersedes the output half of ADR-0742)
    plugin_root, deps_dir = _resolve_paths()
    _use_utf8_output(plugin_root)
    if len(sys.argv) < _MIN_ARGC:
        print(
            "Usage: python3 scripts/launcher.py <module> [--install-deps]",
            file=sys.stderr,
        )
        sys.exit(1)
    module = sys.argv[1]
    if _needs_stand_in(module, deps_dir):
        launcher_mcp_bootstrap.serve([sys.executable, _LAUNCHER, *sys.argv[1:]])
        return
    launcher_python.ensure_supported(deps_dir, _LAUNCHER)
    install_deps = "--install-deps" in sys.argv
    _set_import_paths(plugin_root, deps_dir)
    if (
        module == "mcp_server.hooks.post_tool_capture"
        and not install_deps
        and os.environ.get("CORTEX_CAPTURE_MODE", "full") != "full"
    ):
        from launcher_capture import skip_capture  # noqa: PLC0415 — only non-full capture needs the stdlib preflight

        if skip_capture():
            return
    _apply_backend()
    if module == launcher_ml.WARMUP_MODULE:
        launcher_ml.run_job(
            deps_dir,
            lambda: _ensure_runtime(module, True, deps_dir),
            lambda: _run(module, plugin_root),
        )
        return
    _ensure_runtime(module, install_deps, deps_dir)
    _run(module, plugin_root)


def entrypoint() -> None:
    """Keep cleanup imports and registry I/O out of per-tool hook launches."""
    arguments = sys.argv[1:]
    _use_utf8_output(_resolve_paths()[0])
    if arguments and arguments[0].partition("=")[0] in {
        "--cleanup-deps",
        "--dry-run",
        "--apply",
        "--plugin-id",
    }:
        from launcher_cleanup import cli  # noqa: PLC0415 — explicit maintenance only

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
