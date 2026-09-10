#!/usr/bin/env python3
"""Dependency bootstrap for scripts/launcher.py — stdlib only.

Public entry points used by launcher.py: ``ensure_deps`` (base runtime,
every entry point) and ``ensure_all_deps`` (base + ML stack, SessionStart
only).

source: ADR-0747"""

from __future__ import annotations

import contextlib
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
import launcher_pins as _pins  # noqa: E402
import importlib  # noqa: E402

# source: ADR-0747
_pid_alive = _fs.pid_alive
_normalize_dist_key = _fs.normalize_dist_key
_parse_pip_spec = _fs.parse_pip_spec
_dist_info_versions = _fs.dist_info_versions
_entry_dist_key = _fs.entry_dist_key
_dist_info_satisfies = _fs.dist_info_satisfies
_sweep_stale_backups = _fs.sweep_stale_backups
_prune_superseded_dist_info = _fs.prune_superseded_dist_info

# source: ADR-0747
_numpy_version = _pins.numpy_version
_NUMPY_VERSION = _pins.numpy_version(sys.version_info[:2])
_BASE_PACKAGES = _pins.BASE_PACKAGES
_ML_PACKAGES = _pins.ML_PACKAGES

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


def _pins_satisfied(deps_dir: str, kind: str, pins: list[str]) -> bool:
    """True iff a prior successful bootstrap already covered these pins.

    Precondition: ``pins`` is the exact ordered pip-spec list to install.
    Postcondition: reads the cached presence stamp without importing packages or
    scanning dist-info.

    source: ADR-0747"""
    try:
        with open(_stamp_path(deps_dir, kind), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return False
    py = f"{sys.version_info.major}.{sys.version_info.minor}"
    return data.get("python") == py and data.get("pins") == sorted(pins)


def _write_stamp(deps_dir: str, kind: str, pins: list[str]) -> None:
    payload = {
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "pins": sorted(pins),
    }
    try:
        with open(_stamp_path(deps_dir, kind), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except OSError:
        pass  # best-effort — worst case the next call re-verifies


import launcher_deps_install as _install  # noqa: E402

# source: ADR-0747
_commit_entry = _install.commit_entry
_pip_install = _install.pip_install


def ensure_deps(deps_dir: str) -> None:
    """Install the base runtime if missing (every entry point).

        Precondition: none. Postcondition: every package in
        ``_BASE_PACKAGES`` has a matching ``.dist-info`` inside ``deps_dir``,
        OR a diagnostic was printed to stderr and the caller's own import
        will fail with a clear ImportError.

    source: ADR-0747"""
    os.makedirs(deps_dir, exist_ok=True)
    _sweep_stale_backups(deps_dir)
    pins = [spec for _name, spec in _BASE_PACKAGES]
    if _pins_satisfied(deps_dir, "base", pins):
        return
    missing = [
        spec
        for _name, spec in _BASE_PACKAGES
        if not _dist_info_satisfies(deps_dir, spec)
    ]
    if not missing:
        _write_stamp(deps_dir, "base", pins)
        return
    with _deps_lock(deps_dir):
        # Double-checked: another process may have finished installing
        # while this one waited for the lock.
        if _pins_satisfied(deps_dir, "base", pins):
            return
        missing = [
            spec
            for _name, spec in _BASE_PACKAGES
            if not _dist_info_satisfies(deps_dir, spec)
        ]
        if missing:
            _pip_install(deps_dir, missing)
        if all(_importable(name, deps_dir) for name, _spec in _BASE_PACKAGES):
            _write_stamp(deps_dir, "base", pins)


def ensure_all_deps(deps_dir: str) -> None:
    """Install base + ML dependencies (SessionStart hook only).

        Base constraints keep shared ML transitives (notably numpy) on the same
        pinned version as the base install (residue 3). Failed installs cannot
        receive a success stamp, even when an older ML stack remains importable.

    source: ADR-0747"""
    ensure_deps(deps_dir)
    ml_pins = [spec for _name, spec in _ML_PACKAGES]
    if _pins_satisfied(deps_dir, "ml", ml_pins):
        return
    missing = [
        spec for _name, spec in _ML_PACKAGES if not _dist_info_satisfies(deps_dir, spec)
    ]
    if not missing:
        _write_stamp(deps_dir, "ml", ml_pins)
        return
    with _deps_lock(deps_dir):
        if _pins_satisfied(deps_dir, "ml", ml_pins):
            return
        missing = [
            spec
            for _name, spec in _ML_PACKAGES
            if not _dist_info_satisfies(deps_dir, spec)
        ]
        if missing:
            base_pins = [spec for _name, spec in _BASE_PACKAGES]
            if not _pip_install(deps_dir, missing, constraints=base_pins):
                return  # A failed CPU upgrade must never receive a success stamp.
        if _importable("sentence_transformers", deps_dir) and _importable(
            "flashrank", deps_dir
        ):
            _write_stamp(deps_dir, "ml", ml_pins)
