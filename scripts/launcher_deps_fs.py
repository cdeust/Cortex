#!/usr/bin/env python3
"""Filesystem primitives for the deps-dir bootstrap — stdlib only.

Like ``launcher_deps.py`` and ``launcher.py``, this module runs before
the plugin's own dependencies exist on ``sys.path`` and may import only
the Python standard library.

source: ADR-0748"""

from __future__ import annotations

import contextlib
import importlib.machinery
import os
import re
import shutil
import sysconfig

# Matches the backup basename `_commit_entry` (launcher_deps.py) creates:
# `<entry>.bak-<pid>`, e.g. `numpy.bak-4242` or
# `numpy-2.4.4.dist-info.bak-4242`.
_BACKUP_NAME_RE = re.compile(r"^(?P<entry>.+)\.bak-(?P<pid>\d+)$")

# Matches the interpreter-ABI tag CPython (and, on Windows, ``cp<ver>``)
# bakes into a compiled extension's filename: `speedups.cpython-313-
# darwin.so`, `_frozenlist.cpython-314-x86_64-linux-gnu.so`,
# `_binding.cp313-win_amd64.pyd`. Deliberately excludes the untagged
# `.abi3.so`/`.so`/`.pyd` suffixes -- those are the stable-ABI or
# source-shared forms and are NOT tied to one interpreter build, so a
# file ending only in one of them is never "foreign".
#
# source: https://docs.python.org/3/library/sysconfig.html#sysconfig.get_config_var
#   (EXT_SUFFIX carries the same cpython-<ver>-<platform> shape this
#   matches) -- verified on this machine: sysconfig.get_config_var(
#   "EXT_SUFFIX") == ".cpython-313-darwin.so" under Python 3.13.7/macOS.
_ABI_TAGGED_EXTENSION_RE = re.compile(
    r"\.(?:cpython|cp)-?\d+[\w.-]*\.(?:so|pyd|dylib)$"
)


def pid_alive(pid: int) -> bool:
    """True iff ``pid`` currently identifies a live process. Never
    raises; a permission error (pid exists, owned by another user)
    still counts as alive.

    Duplicated from
    ``mcp_server.infrastructure.session_registry._pid_alive`` rather
    than imported: this module must stay stdlib-only (see module
    docstring), and ``mcp_server`` is an outer layer this bootstrap
    script must never import from.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def normalize_dist_key(name: str) -> str:
    """Fold a distribution or import name to its dist-info key.

    Mirrors the normalization Python's wheel installer uses for
    ``.dist-info`` directory names (PEP 427/503): runs of ``-._`` become
    a single ``_``, case-folded. ``pydantic-settings`` and
    ``pydantic_settings`` both normalize to ``pydantic_settings``,
    matching the on-disk ``pydantic_settings-2.14.0.dist-info``.
    """
    return re.sub(r"[-_.]+", "_", name).strip("_").lower()


def parse_pip_spec(spec: str) -> tuple[str, str]:
    """Split ``'name[extra]==version'`` into ``(dist_key, version)``."""
    name_part, _, version = spec.partition("==")
    name_part = name_part.split("[", 1)[0].strip()
    return normalize_dist_key(name_part), version.strip()


def dist_info_versions(dir_path: str) -> dict[str, str]:
    """Map normalized dist key -> version for every ``*.dist-info`` child.

    Precondition: none; a missing or unreadable directory yields an empty map.
    Postcondition: read-only, without side effects.

    source: ADR-0748"""
    versions: dict[str, str] = {}
    try:
        children = os.listdir(dir_path)
    except OSError:
        return versions
    for name in children:
        if not name.endswith(".dist-info"):
            continue
        base = name[: -len(".dist-info")]
        dist_name, _, version = base.rpartition("-")
        if not dist_name:
            continue
        versions[normalize_dist_key(dist_name)] = version
    return versions


def entry_dist_key(entry: str) -> str:
    """Best-effort normalized dist key for a top-level deps-dir entry."""
    if entry.endswith(".dist-info"):
        base = entry[: -len(".dist-info")]
        dist_name, _, _version = base.rpartition("-")
        return normalize_dist_key(dist_name or base)
    return normalize_dist_key(entry)


def dist_info_satisfies(deps_dir: str, spec: str) -> bool:
    """True iff ``deps_dir``'s OWN ``.dist-info`` already matches ``spec``.

        Precondition: ``spec`` is a pip spec (``name==version``, optionally
        with ``[extras]``). Postcondition: pure filesystem read of
        ``deps_dir`` — never consults ``sys.path``, ``sys.modules``, or does
        any import. A package satisfied only by something ELSE on the
        process's ``sys.path`` (the host interpreter's own global
        site-packages, another PYTHONPATH entry) does not count.

    source: ADR-0748"""
    dist_key, version = parse_pip_spec(spec)
    return dist_info_versions(deps_dir).get(dist_key) == version


def current_extension_abi_suffix() -> str:
    """The running interpreter's own compiled-extension suffix.

    Postcondition: a non-empty string on every CPython build this
    launcher supports; falls back to ``importlib.machinery``'s own
    first (most specific) suffix if the sysconfig var is unset, which
    happens on some embedded/frozen builds.

    source: https://docs.python.org/3/library/sysconfig.html#sysconfig.get_config_var"""
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    if suffix:
        return suffix
    return importlib.machinery.EXTENSION_SUFFIXES[0]


def is_foreign_abi_extension(filename: str, current_suffix: str | None = None) -> bool:
    """True iff ``filename`` is a compiled extension tagged for an
    interpreter ABI other than the one currently running.

        Precondition: none. Postcondition: False for anything that is
        not an interpreter-ABI-tagged extension at all (plain ``.py``,
        a ``.dist-info`` dir, or the untagged ``.abi3.so``/``.so``
        forms -- those are cross-interpreter-compatible by
        construction and are never "foreign"). ``current_suffix``
        defaults to ``current_extension_abi_suffix()``; a caller may
        override it for testing.

    source: ADR-1061"""
    if not _ABI_TAGGED_EXTENSION_RE.search(filename):
        return False
    suffix = (
        current_suffix if current_suffix is not None else current_extension_abi_suffix()
    )
    return not filename.endswith(suffix)


def entry_has_foreign_abi_extension(
    path: str, current_suffix: str | None = None
) -> bool:
    """True iff ``path`` -- a file, or a directory walked recursively
    -- contains any extension module built for a foreign interpreter
    ABI (see ``is_foreign_abi_extension``).

        Precondition: none; a missing path is False. Postcondition:
        read-only, without side effects.

    source: ADR-1061"""
    if os.path.isfile(path):
        return is_foreign_abi_extension(os.path.basename(path), current_suffix)
    if not os.path.isdir(path):
        return False
    for _root, _dirs, files in os.walk(path):
        for name in files:
            if is_foreign_abi_extension(name, current_suffix):
                return True
    return False


def sweep_stale_backups(deps_dir: str) -> None:
    """Best-effort removal of ``*.bak-<pid>`` husks left by a prior commit.

        Precondition: none — a missing/unreadable ``deps_dir`` is a silent
        no-op. Postcondition: every top-level ``<entry>.bak-<pid>`` child of
        ``deps_dir`` whose ``<pid>`` no longer identifies a live process has
        been best-effort removed; a backup whose owning process is still
        alive, or whose name doesn't parse as ``<entry>.bak-<digits>``, is
        left untouched.

    source: ADR-0748"""
    try:
        children = os.listdir(deps_dir)
    except OSError:
        return
    for name in children:
        match = _BACKUP_NAME_RE.match(name)
        if match is None:
            continue
        if pid_alive(int(match.group("pid"))):
            continue
        target = os.path.join(deps_dir, name)
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)
        else:
            with contextlib.suppress(OSError):
                os.remove(target)


def prune_superseded_dist_info(deps_dir: str, committed_entry: str) -> None:
    """Best-effort removal of stale ``dist-info`` siblings after a commit.

        Precondition: ``committed_entry`` is a ``*.dist-info`` basename that
        was JUST successfully committed into ``deps_dir`` (else a no-op).
        Postcondition: every OTHER top-level ``*.dist-info`` child of
        ``deps_dir`` whose normalized dist key matches ``committed_entry``'s
        has been best-effort removed. Non-destructive in the same spirit as
        the commit itself: a sibling this can't remove (e.g. still locked)
        is silently left — this is metadata hygiene, not correctness-
        critical, so it never raises.

    source: ADR-0748"""
    if not committed_entry.endswith(".dist-info"):
        return
    key = entry_dist_key(committed_entry)
    try:
        children = os.listdir(deps_dir)
    except OSError:
        return
    for name in children:
        if name == committed_entry or not name.endswith(".dist-info"):
            continue
        if entry_dist_key(name) != key:
            continue
        shutil.rmtree(os.path.join(deps_dir, name), ignore_errors=True)


def prune_foreign_abi_extensions(
    deps_dir: str, current_suffix: str | None = None
) -> None:
    """Best-effort removal of TOP-LEVEL extension-module files tagged
    for an interpreter ABI other than the one currently running.

        Precondition: none -- a missing/unreadable ``deps_dir`` is a
        silent no-op. Postcondition: every top-level FILE (not
        recursed into directories -- those are handled per-entry by
        the ABI-aware idempotence guard, which replaces the whole
        directory atomically) child of ``deps_dir`` that is a
        foreign-ABI extension has been best-effort removed.

        A ``--target`` install can leave these as loose top-level
        modules with no owning ``.dist-info`` of their own (e.g.
        ``_cffi_backend.cpython-313-darwin.so`` next to a freshly
        committed ``_cffi_backend.cpython-314-darwin.so``): the
        running interpreter can never load a foreign-ABI file, so
        deleting it costs nothing it could still use, and it is
        unconditionally dead weight (issue #540, second shape).

    source: ADR-1061"""
    try:
        children = os.listdir(deps_dir)
    except OSError:
        return
    for name in children:
        path = os.path.join(deps_dir, name)
        if not os.path.isfile(path):
            continue
        if not is_foreign_abi_extension(name, current_suffix):
            continue
        with contextlib.suppress(OSError):
            os.remove(path)
