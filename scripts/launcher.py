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

    Supply-chain safety: all direct packages are pinned to the exact
    releases resolved in uv.lock (see the ``# source: uv.lock``
    comments below).  Pip is given ``--index-url https://pypi.org/simple/``
    so a compromised or custom index cannot shadow the named packages.
    Transitive dependencies are resolved by pip at install time and are
    NOT separately pinned — they are bounded by the exact version of the
    direct package, which limits the attack surface to packages that the
    pinned release would have accepted.

    Full ``--require-hashes`` mode is intentionally NOT used here: pip's
    ``--require-hashes`` requires every package in the dependency
    closure (including pip's own install-time dependencies) to be listed
    with a hash.  At bootstrap time we install only the small set below;
    shipping or generating a complete transitive-closure hash file at
    runtime would add fragile complexity with little security gain over
    exact-version pinning + index locking on the direct installs.
    """
    os.makedirs(deps_dir, exist_ok=True)

    # numpy resolves to two versions in uv.lock depending on Python:
    #   2.2.6 for Python < 3.11  (resolution-marker "python_full_version < '3.11'")
    #   2.4.4 for Python >= 3.11 (all remaining markers)
    # source: uv.lock (numpy blocks at lines ~1968 and ~2033).
    # uv.lock also forks by sys_platform for some packages, but numpy's
    # version split is purely by python_full_version — no platform branch
    # is needed here. This covers the non-win32 install path used by this
    # bootstrap; win32 users are not excluded, and the same versions apply.
    _numpy_version = "2.2.6" if sys.version_info < (3, 11) else "2.4.4"

    # Base runtime (every entry point) + postgres trio (pg_store
    # hard-imports at module load): (import_name, pip_spec).
    # All versions sourced from uv.lock resolved set.
    required = [
        ("fastmcp", "fastmcp==3.2.4"),  # source: uv.lock
        ("pydantic", "pydantic==2.13.3"),  # source: uv.lock
        ("pydantic_settings", "pydantic-settings==2.14.0"),  # source: uv.lock
        ("numpy", f"numpy=={_numpy_version}"),  # source: uv.lock
        ("psycopg", "psycopg[binary]==3.3.3"),  # source: uv.lock
        ("psycopg_pool", "psycopg_pool==3.3.0"),  # source: uv.lock
        ("pgvector", "pgvector==0.4.2"),  # source: uv.lock
    ]
    missing = [spec for name, spec in required if not _importable(name, deps_dir)]
    if not missing:
        return
    _pip_install(deps_dir, missing)


def _importable(import_name: str, deps_dir: str) -> bool:
    """True iff ``import_name`` resolves to a REAL package.

    A bare ``import pkg`` succeeds even for the husk an interrupted
    ``pip install --target`` leaves behind: the package directory
    exists but has no ``__init__.py``, so Python imports it as a
    NAMESPACE package (``__file__ is None``) and every
    ``from pkg import X`` later dies with "unknown location". Because
    deps_dir is first on sys.path, that husk shadows any healthy
    install and the MCP server fails to connect on every retry
    (observed 2026-06-12: deps/fastmcp without __init__.py →
    "cannot import name 'FastMCP' from 'fastmcp' (unknown location)").

    When a husk is detected inside deps_dir it is deleted so the
    reinstall lands clean.
    """
    import importlib

    try:
        mod = importlib.import_module(import_name)
    except ImportError:
        return False
    if getattr(mod, "__file__", None) is not None:
        return True
    # Namespace husk — evict from sys.modules and remove the partial
    # directory if it lives in our deps dir, then report missing.
    sys.modules.pop(import_name, None)
    husk = os.path.join(deps_dir, import_name)
    if os.path.isdir(husk):
        import shutil

        shutil.rmtree(husk, ignore_errors=True)
        print(
            f"[cortex-launcher] removed corrupt partial install: {husk}",
            file=sys.stderr,
        )
    return False


def _pip_install(deps_dir: str, packages: list[str]) -> None:
    """Install ``packages`` into ``deps_dir``, surfacing failures.

    The previous version swallowed pip's output entirely
    (capture_output=True, no returncode check), so on any machine where
    pip fails — corporate proxy, no network, PEP 668
    externally-managed interpreter — the launcher continued, the target
    module died with a bare ImportError, and Claude Code reported only
    "failed to connect" with no cause (observed 2026-06-12).

    PEP 668 interpreters refuse ``pip install`` with an
    ``externally-managed-environment`` error; per PEP 668 the explicit
    user-requested override is ``--break-system-packages``. Installing
    with ``--target`` into the plugin's own deps dir never touches the
    system site-packages, so the override is safe here. We retry with
    the flag only when pip's own error names that condition.

    The install is ATOMIC with respect to deps_dir: pip targets a
    sibling temp dir, and only fully-installed top-level entries are
    moved into deps_dir afterwards. If the launcher is killed
    mid-install (e.g. the MCP client's startup timeout on a slow first
    bootstrap), deps_dir is untouched — the kill leaves an orphan temp
    dir, not the namespace husk that used to shadow every later launch
    (observed 2026-06-12).
    """
    import shutil

    tmp_dir = f"{deps_dir}.tmp-{os.getpid()}"
    # --index-url: constrain installs to the official PyPI index so a
    # custom or compromised index cannot shadow packages via
    # dependency-confusion attacks.
    # Exact == version pinning (sourced from uv.lock) is a VERSION
    # safeguard only: it prevents a newer release from silently running.
    # It does NOT verify content integrity against a compromised index —
    # pip performs no hash check by default. For integrity verification,
    # --require-hashes with a complete transitive hash manifest would be
    # needed; that is intentionally omitted here (see _ensure_deps docstring).
    #
    # The environment passed to pip is sanitized (see clean_env below) to
    # prevent the caller's PIP_INDEX_URL / PIP_EXTRA_INDEX_URL /
    # PIP_CONFIG_FILE from overriding --index-url and re-opening the
    # dependency-confusion vector.
    clean_env = dict(os.environ)
    for _var in (
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_CONFIG_FILE",
        "PIP_FIND_LINKS",
        "PIP_TRUSTED_HOST",
    ):
        clean_env.pop(_var, None)
    base = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-q",
        "--index-url",
        "https://pypi.org/simple/",
        "--target",
        tmp_dir,
        *packages,
    ]
    try:
        proc = subprocess.run(base, capture_output=True, text=True, env=clean_env)
        err = (proc.stderr or "") + (proc.stdout or "")
        if proc.returncode != 0 and "externally-managed-environment" in err:
            # PEP 668 (https://peps.python.org/pep-0668/) interpreters
            # refuse bare ``pip install`` with an
            # ``externally-managed-environment`` error.  Installing with
            # ``--target`` writes into the plugin's own deps dir (never
            # system site-packages), so the override is safe.  We warn
            # prominently so the operator is aware — this is NOT a silent
            # fallback.
            print(
                "[cortex-launcher] WARNING: pip reports an "
                "externally-managed Python environment (PEP 668). "
                "The Cortex plugin installs dependencies into its own "
                "private directory (not system site-packages), so "
                "--break-system-packages is safe here. "
                "Retrying with that flag now. "
                "If you want to suppress this retry, pre-install the "
                f"packages yourself: {', '.join(packages)}",
                file=sys.stderr,
            )
            proc = subprocess.run(
                base + ["--break-system-packages"],
                capture_output=True,
                text=True,
                env=clean_env,
            )
            err = (proc.stderr or "") + (proc.stdout or "")
        if proc.returncode != 0:
            print(
                "[cortex-launcher] dependency install failed for "
                f"{', '.join(packages)} (python {sys.executable}).\n"
                f"[cortex-launcher] pip said:\n{err.strip()[-2000:]}\n"
                "[cortex-launcher] Fix the pip failure above (network/"
                "proxy/permissions), or pre-install the packages, then "
                "reconnect the cortex MCP server.",
                file=sys.stderr,
            )
            return
        # Commit: move each fully-installed entry into deps_dir.
        for entry in os.listdir(tmp_dir):
            dest = os.path.join(deps_dir, entry)
            if os.path.isdir(dest):
                shutil.rmtree(dest, ignore_errors=True)
            elif os.path.exists(dest):
                os.remove(dest)
            os.replace(os.path.join(tmp_dir, entry), dest)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _ensure_all_deps(deps_dir: str) -> None:
    """Install all dependencies including ML packages."""
    _ensure_deps(deps_dir)
    if not _importable("sentence_transformers", deps_dir):
        # source: uv.lock (sentence-transformers and flashrank blocks)
        _pip_install(
            deps_dir,
            ["sentence-transformers==5.4.1", "flashrank==0.2.10"],
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
