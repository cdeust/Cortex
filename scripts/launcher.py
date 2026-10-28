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
import launcher_base_job  # noqa: E402
import launcher_deps  # noqa: E402
import launcher_layout  # noqa: E402
import launcher_maintain  # noqa: E402
import launcher_mcp_bootstrap  # noqa: E402
import launcher_ml  # noqa: E402
import launcher_python  # noqa: E402
import launcher_setup  # noqa: E402
import launcher_site  # noqa: E402

_MIN_ARGC = 2  # source: ADR-0742
_LAUNCHER = str(
    Path(__file__).resolve()
)  # source: ADR-1104 (re-exec and background job target)


# The launches that may install: the MCP server (its host waits on the stand-in,
# not on this process) and the two detached jobs. Every other module is a hook
# inside a host time budget and never installs (source: ADR-1108).
_INSTALLING = frozenset(
    {
        "mcp_server",
        launcher_ml.WARMUP_MODULE,
        launcher_base_job.JOB,
        launcher_setup.SETUP,
    }
)


def _resolve_paths() -> tuple[str, str]:
    """Resolve plugin root and the deps directory of its locked set.

    Postcondition: the deps directory is ``<data>/sets/<key>``, ``<key>``
    naming this plugin tree's uv.lock set (``launcher_layout``), so two
    plugin versions locking one set share it and a different set never
    shares one. source: ADR-1108
    """
    # CLAUDE_PLUGIN_ROOT is set by Claude Code for plugins
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if not plugin_root or not Path(plugin_root).is_dir():
        # Fall back to this script's parent's parent
        plugin_root = str(Path(__file__).resolve().parent.parent)

    # CLAUDE_PLUGIN_DATA is set by Claude Code — persistent across updates
    data = os.environ.get("CLAUDE_PLUGIN_DATA", "") or plugin_root
    key = launcher_deps.lock_key() or launcher_layout.NO_LOCK
    return plugin_root, launcher_layout.deps_dir(data, key)


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


def _ensure_runtime(module: str, install_deps: bool, deps_dir: str) -> None:
    """The dependency sets ``module`` needs, then semantic search in background.

    Precondition: ``module`` is a hook, the MCP server or a job.
    Postcondition: a hook returns only when the base set is installed and
    installs nothing (otherwise ``launcher_base_job.refuse`` exits: 0 with a
    notice for a gate and SessionStart, 1 for every other hook);
    the server installs the base set; the semantic-search job and
    ``--install-deps`` install base + ML. The SessionStart launch then starts
    the semantic-search job and tells the hook where it stands.
    source: ADR-0742
    source: ADR-1104
    source: ADR-1108
    """
    if install_deps:
        launcher_deps.ensure_all_deps(deps_dir)
    elif module in _INSTALLING:
        launcher_deps.ensure_deps(deps_dir)
    else:
        launcher_base_job.require_ready(deps_dir, _LAUNCHER, module)
    # The import system cached deps_dir as it was before this install
    # (source: ADR-1104).
    importlib.invalidate_caches()
    # The locked set just installed can add a .pth (~0.5 ms). source: issue #621
    launcher_site.isolate_deps(deps_dir)
    if module == "mcp_server.hooks.session_start":
        semantic, detail = launcher_ml.start(deps_dir, _LAUNCHER)
        os.environ["CORTEX_SEMANTIC_SEARCH"] = semantic
        os.environ["CORTEX_SEMANTIC_SEARCH_DETAIL"] = detail
        # source: ADR-1114 D3 — an eligible store Setup left on SQLite says why
        fallback = launcher_setup.sqlite_fallback(deps_dir)
        if fallback and os.environ.get("CORTEX_MEMORY_STORE_BACKEND") == "sqlite":
            os.environ["CORTEX_SQLITE_FALLBACK"] = fallback


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


def _require_python(module: str, install_deps: bool, deps_dir: str) -> None:
    """Return on a supported Python (re-executing onto the managed one).

    A hook never downloads one: with none installed it refuses (ADR-1108).
    """
    try:
        launcher_python.ensure_supported(
            deps_dir, _LAUNCHER, may_provide=install_deps or module in _INSTALLING
        )
    except launcher_python.NotProvidedError as exc:
        launcher_base_job.refuse(deps_dir, _LAUNCHER, str(exc), module)


def _skips_capture(module: str, install_deps: bool) -> bool:
    """The capture hook, in a non-full capture mode, may skip before any import."""
    if (
        module != "mcp_server.hooks.post_tool_capture"
        or install_deps
        or os.environ.get("CORTEX_CAPTURE_MODE", "full") == "full"
    ):
        return False
    from launcher_capture import skip_capture  # noqa: PLC0415 — only non-full capture needs the stdlib preflight

    return skip_capture()


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
    if module == launcher_setup.SETUP:
        launcher_setup.require_host_data()
    if module == launcher_maintain.JOB:  # stdlib only: any Python runs it
        sys.exit(launcher_maintain.main(plugin_root, deps_dir))
    if _needs_stand_in(module, deps_dir):
        launcher_mcp_bootstrap.serve([sys.executable, _LAUNCHER, *sys.argv[1:]])
        return
    install_deps = "--install-deps" in sys.argv
    _require_python(module, install_deps, deps_dir)
    _set_import_paths(plugin_root, deps_dir)
    jobs = {
        launcher_base_job.JOB: launcher_base_job.run,
        launcher_setup.SETUP: launcher_setup.run,
    }
    if module in jobs:
        sys.exit(jobs[module](deps_dir, _LAUNCHER))
    if _skips_capture(module, install_deps):
        return
    launcher_backend.apply()
    if module == launcher_ml.WARMUP_MODULE:
        launcher_ml.run_job(
            deps_dir,
            lambda: _ensure_runtime(module, True, deps_dir),
            lambda: _run(module, plugin_root),
        )
        return
    _ensure_runtime(module, install_deps, deps_dir)
    launcher_maintain.after_runtime(module, plugin_root, deps_dir, _LAUNCHER)
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
