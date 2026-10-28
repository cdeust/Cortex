#!/usr/bin/env python3
"""Check the supported plugin runtime on an isolated home, without ML downloads.

Uses the launcher's pinned Python and locked base set (ADR-1092), then its real
managed PostgreSQL provisioning step. ADR-1114 explicitly supports SQLite on
native Windows; PostgreSQL provisioning failures on supported hosts fail CI.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import site
import subprocess
import sys

import launcher_deps
import launcher_layout
import launcher_python

ROOT = Path(__file__).resolve().parent.parent


def isolated_environment(work: Path, inherited: dict[str, str]) -> dict[str, str]:
    kept = (
        "PATH",
        "SystemRoot",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "LANG",
        "LC_ALL",
        "TERM",
        "USER",
        "LOGNAME",
        "USERNAME",
        "USERDOMAIN",
    )
    env = {key: inherited[key] for key in kept if key in inherited}
    home = work / "home"
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        CLAUDE_CONFIG_DIR=str(home / ".claude"),
        CORTEX_CLAUDE_DIR=str(home / ".claude"),
        CLAUDE_PLUGIN_ROOT=str(ROOT),
        CLAUDE_PLUGIN_DATA=str(work / "data"),
        TMPDIR=str(work / "tmp"),
        TMP=str(work / "tmp"),
        TEMP=str(work / "tmp"),
        PYTHONNOUSERSITE="1",
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
        UV_CACHE_DIR=str(work / "uv-cache"),
    )
    return env


def run_isolated(work: Path) -> int:
    work.mkdir(parents=True, exist_ok=False)
    for name in ("home", "tmp", "data"):
        (work / name).mkdir()
    return subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--work",
            str(work),
            "--bootstrap",
        ],
        cwd=work,
        env=isolated_environment(work, dict(os.environ)),
        check=False,
    ).returncode


def bootstrap(work: Path) -> int:

    deps = launcher_layout.project_deps_dir(work / "data", ROOT)
    python = launcher_python.provide(deps)
    return subprocess.run(
        [python, str(Path(__file__).resolve()), "--work", str(work), "--check"],
        cwd=work,
        check=False,
    ).returncode


def require_backend(outcome, marker, *, windows: bool) -> None:
    if outcome.failed:
        raise RuntimeError(outcome.failed)
    if windows:
        if not outcome.fallback.startswith("managed PostgreSQL unavailable here ("):
            raise RuntimeError(
                "Windows must report its unsupported managed PostgreSQL host"
            )
        if marker is None or marker.get("backend") != "sqlite":
            raise RuntimeError(
                "Windows launcher did not select its supported SQLite store"
            )
        print("SQLite fallback:", outcome.fallback)
    elif outcome.fallback or marker is None or marker.get("backend") != "managed":
        raise RuntimeError(
            f"Supported host did not provision managed PostgreSQL: {outcome}"
        )


def stop_owned_server(paths) -> None:
    from mcp_server.infrastructure import managed_pg  # noqa: PLC0415 — loaded only after the locked base install

    managed_pg.detach()
    if os.name != "nt" and paths.root.is_dir():
        descriptor = managed_pg.open_lock(paths.lock("supervisor"))
        try:
            # Supervisor releases this only after its PostgreSQL child has exited.
            managed_pg.flock(descriptor, exclusive=True)
        finally:
            os.close(descriptor)


def check_windows_bash_contract() -> None:
    """Issue #689: run actual manifest hook commands under PowerShell without bash."""
    if os.name == "nt":
        subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(ROOT / "scripts" / "ci_windows_bash.ps1"),
                "-Python",
                sys.executable,
                "-Root",
                str(ROOT),
            ],
            cwd=ROOT,
            check=True,
        )


def check(work: Path) -> int:

    deps = launcher_layout.project_deps_dir(work / "data", ROOT)
    site.addsitedir(deps)
    launcher_deps.ensure_deps(deps)
    sys.path.insert(0, str(ROOT))
    import launcher_backend  # noqa: PLC0415 — requires the installed runtime
    import launcher_pg_provision  # noqa: PLC0415 — requires the installed runtime
    from mcp_server import doctor  # noqa: PLC0415 — must observe the isolated home
    from mcp_server.shared.platform import resolve_bash  # noqa: PLC0415 — requires the checked-out runtime
    from mcp_server.infrastructure import backend_marker, managed_pg  # noqa: PLC0415 — must observe the isolated home

    paths = managed_pg.root_under(backend_marker.BACKEND_MARKER_PATH.parent)
    try:
        # Exercise the actual host binary, including Git Bash on Windows.
        subprocess.run([resolve_bash(), "-c", "exit 0"], check=True)
        check_windows_bash_contract()
        outcome = launcher_pg_provision.setup_step(str(work / "data"), print)
        launcher_backend.apply()
        require_backend(
            outcome, backend_marker.read_backend_marker(), windows=os.name == "nt"
        )
        return doctor.run()
    finally:
        stop_owned_server(paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    work = args.work.resolve()
    if args.check:
        return check(work)
    if args.bootstrap:
        return bootstrap(work)
    return run_isolated(work)


if __name__ == "__main__":
    raise SystemExit(main())
