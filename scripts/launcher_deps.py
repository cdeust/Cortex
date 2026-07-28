#!/usr/bin/env python3
"""Dependency bootstrap for scripts/launcher.py — stdlib only.

Runs BEFORE the plugin's own dependencies exist on ``sys.path``, so this
module (like launcher.py itself) may import only the Python standard
library — no fastmcp, no pydantic, no numpy. The exceptions are its two
stdlib-only siblings, split out for SRP and the 500-line file-size rule:
``launcher_deps_fs`` (pure filesystem primitives — dist-info parsing,
backup sweeping, superseded-metadata pruning) and
``launcher_deps_install`` (the two I/O-heavy steps of one install: pip
invocation into a scratch dir, then committing its result). THIS module
owns the policy layer — stamping, locking, and deciding WHEN to call
either sibling.

Public entry points used by launcher.py: ``ensure_deps`` (base runtime,
every entry point) and ``ensure_all_deps`` (base + ML stack, SessionStart
only).

Source: issue #97 (reporter mbe14, Windows 11). The prior commit step
blindly ``rmtree``'d and ``os.replace``'d every top-level entry pip just
resolved into a temp dir, including transitive deps (e.g. numpy, pulled
in by sentence-transformers) that were already correctly installed and
in-use by a concurrently-running MCP server process. On Windows the
server's imported ``.pyd`` files are locked, so the ``os.replace`` failed
mid-loop, and the pre-existing ``finally: shutil.rmtree(tmp_dir)`` then
destroyed the freshly-downloaded replacement too — leaving deps_dir with
neither the old nor the new package, and every later hook re-attempting
and re-failing the same multi-hundred-MB install for the rest of the
session.

Three residues from mbe14's real-Windows-lock verification of that fix
(all fixed here): (1) a locked file inside a rename-aside backup left a
``*.bak-<pid>`` husk behind — swept opportunistically at the start of
every bootstrap; (2) a cross-version commit left the OLD ``.dist-info``
next to the new one — pruned right after a successful commit; (3) the
missing-package decision searched the whole process ``sys.path``, so a
pin already satisfied by the HOST's global site-packages was silently
dropped from the install set and only ever entered ``deps_dir`` as an
UNPINNED transitive — the decision is now based on ``deps_dir``'s own
dist-info only, plus a pip constraints file on the ML install so a
shared transitive (numpy) agrees with the base pin regardless of
install order.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

# launcher_deps_fs.py is a stdlib-only sibling module (filesystem
# primitives extracted for SRP + the 500-line file-size rule).
# Path-based import for the same reason launcher.py path-imports THIS
# module: resolves identically whether this file is run through
# launcher.py (script dir already on sys.path) or loaded directly via
# importlib.util.spec_from_file_location from a test.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import launcher_deps_fs as _fs  # noqa: E402
import importlib  # noqa: E402

# Re-exported at the original names: these were this module's own
# private helpers before the SRP split and remain part of its tested
# surface (see tests_py/scripts/test_launcher_deps.py).
_pid_alive = _fs.pid_alive
_normalize_dist_key = _fs.normalize_dist_key
_parse_pip_spec = _fs.parse_pip_spec
_dist_info_versions = _fs.dist_info_versions
_entry_dist_key = _fs.entry_dist_key
_dist_info_satisfies = _fs.dist_info_satisfies
_sweep_stale_backups = _fs.sweep_stale_backups
_prune_superseded_dist_info = _fs.prune_superseded_dist_info

# numpy resolves to two versions in uv.lock depending on Python:
#   2.2.6 for Python < 3.11  (resolution-marker "python_full_version < '3.11'")
#   2.4.4 for Python >= 3.11 (all remaining markers)
# source: uv.lock (numpy blocks at lines ~1968 and ~2033).
_NUMPY_VERSION = "2.2.6" if sys.version_info < (3, 11) else "2.4.4"

# Base runtime (every entry point) + postgres trio (pg_store hard-imports
# at module load): (import_name, pip_spec). All versions sourced from
# uv.lock resolved set.
_BASE_PACKAGES: list[tuple[str, str]] = [
    ("fastmcp", "fastmcp==3.2.4"),  # source: uv.lock
    ("pydantic", "pydantic==2.13.3"),  # source: uv.lock
    ("pydantic_settings", "pydantic-settings==2.14.0"),  # source: uv.lock
    ("numpy", f"numpy=={_NUMPY_VERSION}"),  # source: uv.lock
    ("psycopg", "psycopg[binary]==3.3.3"),  # source: uv.lock
    ("psycopg_pool", "psycopg_pool==3.3.0"),  # source: uv.lock
    ("pgvector", "pgvector==0.4.2"),  # source: uv.lock
]

# ML stack — SessionStart-only. source: uv.lock (sentence-transformers
# and flashrank blocks).
_ML_PACKAGES: list[tuple[str, str]] = [
    ("sentence_transformers", "sentence-transformers==5.4.1"),
    ("flashrank", "flashrank==0.2.10"),
]

_STALE_LOCK_SECONDS = 120  # abandon a lock older than this (crashed holder)
_LOCK_WAIT_SECONDS = 30  # give up waiting and proceed unlocked past this


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
    reinstall lands clean. This is deliberately import-based (not a
    dist-info probe) because husk detection needs the real import
    machinery. Used only as the POST-install verification (issue #97
    residue 3): the missing-package DECISION is dist-info-based (see
    ``_dist_info_satisfies``) so the cold/common-case path never pays
    an import cost or searches the host's global site-packages.
    """

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

    Precondition: none. Postcondition: on normal exit the lock directory
    is removed; on an unbounded wait (another process holds a live lock
    past ``_LOCK_WAIT_SECONDS``) this proceeds WITHOUT the lock rather
    than blocking forever — a SessionStart hook has a bounded timeout
    (30s, .claude-plugin/plugin.json) and a permanently-hung bootstrap is
    worse than the historical race this lock narrows.

    Uses ``os.mkdir`` (atomic on every platform CPython supports,
    including Windows) rather than a POSIX-only ``fcntl`` flock, per the
    stdlib-only constraint at the top of this module.

    Rationale for the lock at all: issue #97's race is the SessionStart
    hook and the MCP server both discovering missing base deps at the
    very first boot and calling ``_pip_install`` concurrently — the
    idempotence guard below (skip-if-dest-already-matches) closes the
    common case, but two processes racing to be FIRST still need
    serialization so only one of them performs the commit.
    """
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

    Precondition: ``pins`` is the exact, ordered pip-spec list this call
    would install. Postcondition: pure read (no import, no dist-info
    scan) — this is the "cheaper presence probe" (issue #97 suggestion
    4): once written, later calls in the same session (and across
    sessions, until a Cortex release bumps a pin) skip
    ``_importable``/dist-info work entirely.

    A stamp is trusted only for the exact pin set and Python minor
    version that produced it — "un stamp par version de pin suffit"
    (issue #97): any pin bump (new Cortex release) or interpreter change
    invalidates it and the full check runs again, self-healing.
    """
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

# Re-exported at the original names for the same reason as the
# launcher_deps_fs re-exports above: these were this module's own
# private helpers before the SRP split.
_commit_entry = _install.commit_entry
_pip_install = _install.pip_install


def ensure_deps(deps_dir: str) -> None:
    """Install the base runtime if missing (every entry point).

    Precondition: none. Postcondition: every package in
    ``_BASE_PACKAGES`` has a matching ``.dist-info`` inside ``deps_dir``,
    OR a diagnostic was printed to stderr and the caller's own import
    will fail with a clear ImportError.

    The stamp check is a pure file read — issue #97's "one-time
    bootstrap with a success stamp" (suggestion 3) applied to the base
    stack too: after the first successful boot, every later hook/server
    launch in the same install skips the dist-info scan entirely. The
    missing-package decision itself is dist-info-based (residue 3, see
    ``_dist_info_satisfies``); ``_importable`` is still used ONLY as the
    post-install verification — real husk detection (a corrupted
    namespace-package install) is worth the import cost right after
    ``pip`` has actually run, unlike on the cold/common-case path this
    fix removes it from.
    """
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

    Precondition/postcondition: same shape as ``ensure_deps``, extended
    to ``_ML_PACKAGES``. Kept out of the hot path for every OTHER hook
    (issue #97 suggestion 3) — only SessionStart and explicit
    ``--install-deps`` invoke this.

    The ML install passes the base pins as pip constraints (residue 3,
    second half): without them, an ML transitive dependency shared with
    the base stack (numpy, via sentence-transformers) resolves freely
    and can disagree with the version the base install already
    committed. Constraining the ML resolve to the base pins keeps a
    shared transitive on the SAME pinned version regardless of install
    order.
    """
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
            _pip_install(deps_dir, missing, constraints=base_pins)
        if _importable("sentence_transformers", deps_dir) and _importable(
            "flashrank", deps_dir
        ):
            _write_stamp(deps_dir, "ml", ml_pins)
