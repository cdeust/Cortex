#!/usr/bin/env python3
"""Dependency bootstrap for scripts/launcher.py — stdlib only.

Public entry points used by launcher.py: ``ensure_deps`` (base runtime,
every entry point) and ``ensure_all_deps`` (base + ML stack, SessionStart
only). ``install_installer_set``, also run as ``python3 launcher_deps.py
DEPS_DIR``, is the installers' path into the same directory. Every set is
read from uv.lock through ``launcher_uv``; a stamp keyed on uv.lock's
digest keeps the hot path free of any subprocess.

source: ADR-0747
source: ADR-1063
source: ADR-1092"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

# source: ADR-0747
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import launcher_deps_fs as _fs  # noqa: E402
import launcher_sets as _sets  # noqa: E402
import importlib  # noqa: E402

# source: ADR-0747
_pid_alive = _fs.pid_alive
_normalize_dist_key = _fs.normalize_dist_key
_dist_info_versions = _fs.dist_info_versions
_entry_dist_key = _fs.entry_dist_key
_sweep_stale_backups = _fs.sweep_stale_backups
_prune_superseded_dist_info = _fs.prune_superseded_dist_info

LOCK_PATH = Path(_SCRIPTS_DIR).parent / "uv.lock"

_STALE_LOCK_SECONDS = 120  # abandon a lock older than this (crashed holder)
_LOCK_WAIT_SECONDS = 30  # give up waiting and proceed unlocked past this


def _importable(import_name: str, deps_dir: str) -> bool:
    """True iff ``import_name`` resolves to a REAL package.

    source: ADR-0747"""

    try:
        mod = importlib.import_module(import_name)
    except ImportError:
        return False
    if getattr(mod, "__file__", None) is not None:
        return True
    sys.modules.pop(import_name, None)
    husk = os.path.join(deps_dir, import_name)
    if os.path.isdir(husk):
        shutil.rmtree(husk, ignore_errors=True)
        print(
            f"[cortex-launcher] removed corrupt partial install: {husk}",
            file=sys.stderr,
        )
    return False


@contextlib.contextmanager
def _deps_lock(deps_dir: str):
    """Cross-platform mutual exclusion around install+commit.

    Precondition: none.
    Postcondition: removes the lock directory on normal exit. If another process holds a
    live lock beyond ``_LOCK_WAIT_SECONDS``, continues without the lock.

    source: ADR-0747"""
    lock_dir = f"{deps_dir}.lock"
    stamp_file = os.path.join(lock_dir, "holder")
    deadline = time.monotonic() + _LOCK_WAIT_SECONDS
    acquired = False
    while time.monotonic() < deadline:
        try:
            os.mkdir(lock_dir)
            acquired = True
            break
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(stamp_file)
            except OSError:
                age = 0.0
            if age > _STALE_LOCK_SECONDS:
                shutil.rmtree(lock_dir, ignore_errors=True)
                continue
            time.sleep(0.2)
    if acquired:
        try:
            with open(stamp_file, "w", encoding="utf-8") as fh:
                fh.write(f"{os.getpid()} {time.time()}")
        except OSError:
            pass
    try:
        yield acquired
    finally:
        if acquired:
            shutil.rmtree(lock_dir, ignore_errors=True)


def _stamp_path(deps_dir: str, kind: str) -> str:
    return os.path.join(deps_dir, f".cortex-deps-stamp-{kind}.json")


def lock_digest() -> str | None:
    """sha256 of uv.lock, or None when the plugin tree carries no lock."""
    try:
        return hashlib.sha256(LOCK_PATH.read_bytes()).hexdigest()
    except OSError:
        return None


def _stamp_matches(deps_dir: str, kind: str, digest: str) -> bool:
    """True iff a prior successful install of ``kind`` used this exact lock.

    source: ADR-0747
    source: ADR-1092"""
    try:
        data = json.loads(Path(_stamp_path(deps_dir, kind)).read_bytes())
    except (OSError, ValueError):
        return False
    py = f"{sys.version_info.major}.{sys.version_info.minor}"
    return data.get("python") == py and data.get("lock") == digest


def _write_stamp(deps_dir: str, kind: str, digest: str) -> None:
    payload = {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "lock": digest,
    }
    try:
        Path(_stamp_path(deps_dir, kind)).write_bytes(json.dumps(payload).encode())
    except OSError:
        pass  # best-effort — worst case the next call re-verifies


import launcher_deps_install as _install  # noqa: E402

# source: ADR-0747
_commit_entry = _install.commit_entry
_install_locked_set = _install.install_locked_set


def _ensure(
    deps_dir: str, kind: str, set_args: tuple[str, ...], imports: tuple[str, ...]
) -> None:
    """Install one uv.lock set unless this lock already stamped it.

        Postcondition: the ``kind`` stamp names the current uv.lock digest
        iff the set installed and every name in ``imports`` imports; a
        failure prints its cause and leaves the caller's import to fail.

    source: ADR-0747
    source: ADR-1092"""
    os.makedirs(deps_dir, exist_ok=True)
    _sweep_stale_backups(deps_dir)
    digest = lock_digest()
    if digest is None:
        print(
            f"[cortex-launcher] {LOCK_PATH} is missing; cannot install "
            "dependencies. Reinstall the plugin.",
            file=sys.stderr,
        )
        return
    if _stamp_matches(deps_dir, kind, digest):
        return
    with _deps_lock(deps_dir):
        # Double-checked: another process may have finished installing
        # while this one waited for the lock.
        if _stamp_matches(deps_dir, kind, digest):
            return
        if not _install_locked_set(deps_dir, set_args):
            return  # A failed install must never receive a success stamp.
        if all(_importable(name, deps_dir) for name in imports):
            _write_stamp(deps_dir, kind, digest)


def ensure_deps(deps_dir: str) -> None:
    """Install the base runtime set (every entry point).

    source: ADR-0747"""
    _ensure(deps_dir, "base", _sets.BASE, _sets.BASE_IMPORTS)


def ensure_all_deps(deps_dir: str) -> None:
    """Install base + ML sets (SessionStart hook only).

    source: ADR-0747"""
    ensure_deps(deps_dir)
    _ensure(deps_dir, "ml", _sets.ML, _sets.ML_IMPORTS)


def install_installer_set(deps_dir: str) -> bool:
    """Install the installers' set for scripts/setup.sh and setup.py.

    source: ADR-1063
    source: ADR-1092"""
    os.makedirs(deps_dir, exist_ok=True)
    _sweep_stale_backups(deps_dir)
    with _deps_lock(deps_dir):
        return _install_locked_set(deps_dir, _sets.INSTALLER)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=install_installer_set.__doc__)
    parser.add_argument("deps_dir")
    args = parser.parse_args(argv)
    return 0 if install_installer_set(args.deps_dir) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
