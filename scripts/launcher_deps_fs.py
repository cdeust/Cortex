#!/usr/bin/env python3
"""Filesystem primitives for the deps-dir bootstrap — stdlib only.

Split out of ``scripts/launcher_deps.py`` for SRP (issue #97 residues
1-3, reporter mbe14) and the 500-line file-size rule: this module owns
pure filesystem READS/WRITES about ``deps_dir``'s own contents —
dist-info version parsing, backup-husk sweeping, superseded-metadata
pruning — with zero pip/subprocess/lock concerns. ``launcher_deps.py``
owns install ORCHESTRATION (locking, pip invocation, commit) and calls
into this module as its filesystem source of truth.

Like ``launcher_deps.py`` and ``launcher.py``, this module runs before
the plugin's own dependencies exist on ``sys.path`` and may import only
the Python standard library.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import pathlib

# Matches the backup basename `_commit_entry` (launcher_deps.py) creates:
# `<entry>.bak-<pid>`, e.g. `numpy.bak-4242` or
# `numpy-2.4.4.dist-info.bak-4242`.
_BACKUP_NAME_RE = re.compile(r"^(?P<entry>.+)\.bak-(?P<pid>\d+)$")


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

    Precondition: none — a missing/unreadable dir yields an empty map.
    Postcondition: pure read, no side effects. Used both for the
    idempotence guard (issue #97 suggestion 1) and the stamp-free
    presence check.
    """
    versions: dict[str, str] = {}
    try:
        children = [p.name for p in pathlib.Path(dir_path).iterdir()]
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

    Source: issue #97 residue 3 (reporter mbe14, "the substantial one").
    The prior missing-package decision used an import-based probe, which
    searches the WHOLE ``sys.path`` — on the reporter's box a base pin
    (numpy) already satisfied by the HOST's global site-packages was
    dropped from the install set, so it only ever entered ``deps_dir``
    later as an UNPINNED transitive (pulled in by
    pgvector/sentence-transformers), landing on whatever version pip's
    resolver happened to pick for that transitive edge rather than the
    declared pin. ``deps_dir`` content then depended on "resolution
    luck" from the host's unrelated global packages. Basing the
    decision on ``deps_dir``'s own dist-info — the same source of truth
    the stamp check already trusts — makes the bootstrap hermetic
    regardless of what else is importable on the machine.
    """
    dist_key, version = parse_pip_spec(spec)
    return dist_info_versions(deps_dir).get(dist_key) == version


def sweep_stale_backups(deps_dir: str) -> None:
    """Best-effort removal of ``*.bak-<pid>`` husks left by a prior commit.

    Precondition: none — a missing/unreadable ``deps_dir`` is a silent
    no-op. Postcondition: every top-level ``<entry>.bak-<pid>`` child of
    ``deps_dir`` whose ``<pid>`` no longer identifies a live process has
    been best-effort removed; a backup whose owning process is still
    alive, or whose name doesn't parse as ``<entry>.bak-<digits>``, is
    left untouched.

    Source: issue #97 residue 1 (reporter mbe14, verified on real
    Windows locks). When a locked file lives inside the rename-aside
    backup the commit step creates, its own success-path
    ``shutil.rmtree(backup, ignore_errors=True)`` silently keeps
    whatever it could not delete (there: ``numpy.bak-<pid>`` reduced to
    the still-mapped ``.pyd`` files). Once the locking process exits the
    remainder is pure dead weight. Mirrors the pid-parse-then-liveness
    pattern of ``benchmarks/reproduce.sh``'s
    ``sweep_orphaned_containers`` — run opportunistically at the start
    of every bootstrap rather than at commit time, since the lock is
    typically still held by another live process at that exact moment.
    """
    try:
        children = list(pathlib.Path(deps_dir).iterdir())
    except OSError:
        return
    for target in children:
        match = _BACKUP_NAME_RE.match(target.name)
        if match is None:
            continue
        if pid_alive(int(match.group("pid"))):
            continue
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            with contextlib.suppress(OSError):
                target.unlink()


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

    Source: issue #97 residue 2 (reporter mbe14). A cross-version commit
    (e.g. numpy 2.4.4 -> 2.5.1) only ever iterates ``tmp_dir``'s
    entries — the OLD ``numpy-2.4.4.dist-info`` isn't one of them, so it
    was never touched and survived next to the new one, leaving
    duplicate metadata for a single distribution (importlib.metadata and
    pip both see two records for "numpy").
    """
    if not committed_entry.endswith(".dist-info"):
        return
    key = entry_dist_key(committed_entry)
    try:
        children = [p.name for p in pathlib.Path(deps_dir).iterdir()]
    except OSError:
        return
    for name in children:
        if name == committed_entry or not name.endswith(".dist-info"):
            continue
        if entry_dist_key(name) != key:
            continue
        shutil.rmtree(pathlib.Path(deps_dir) / name, ignore_errors=True)
