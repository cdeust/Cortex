#!/usr/bin/env python3
"""Pip invocation and non-destructive commit — stdlib only.

Split out of ``scripts/launcher_deps.py`` for SRP and the 500-line
file-size rule: this module owns the two I/O-heavy steps of a
dependency install — spawning ``pip`` into a scratch dir and committing
its result into ``deps_dir`` one entry at a time — while
``launcher_deps.py`` owns the higher-level policy (stamping, locking,
when to call this at all) and ``launcher_deps_fs.py`` owns pure
filesystem primitives this module reads/writes through.

Like its siblings, this module runs before the plugin's own
dependencies exist on ``sys.path`` and may import only the Python
standard library.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
import launcher_deps_fs as _fs  # noqa: E402
import launcher_pip as _pip  # noqa: E402
import launcher_torch_cpu as _cpu  # noqa: E402

# source: pre-W2-5 pip_install retained the last 2000 characters of pip errors.
_PIP_ERROR_TAIL_CHARS = 2000


def constraint_without_extras(spec: str) -> str:
    """Drop the ``[extra]`` clause from a pip spec, keeping the version.

    Precondition: ``spec`` is a pip requirement string. Postcondition: the
    return value carries no extras clause; everything else is unchanged.

    pip documents constraints files as version-only and now rejects extras
    outright, so ``psycopg[binary]==3.3.4`` (BASE_PACKAGES) failed the whole
    ML install — silently, since only that install passes constraints:
    FlashRank never landed and recall degraded to first-stage scores.

    Stripping preserves the intent rather than changing it — a constraint
    pins the VERSION a shared transitive resolves to, and pip applies it to
    the distribution however its extras were requested; extras belong on the
    install target (which still carries them), not on the constraint.

    # source: https://pip.pypa.io/en/stable/user_guide/#constraints-files
    #   ("only control which version of a requirement is installed")
    # source: measured 2026-08-02 — pip 26.0.1/py3.14 aborted the plugin's
    #   ML install with "ERROR: Constraints cannot have extras"; reproduced
    #   on pip 25.2/py3.13 (`--dry-run --no-index -c <BASE_PACKAGES>`), so
    #   the range is not pip-26-only. Both accept the stripped file.
    """
    head, bracket, rest = spec.partition("[")
    if not bracket:
        return spec
    _dropped, closing, tail = rest.partition("]")
    if not closing:
        return spec  # unbalanced — not ours to rewrite; hand it to pip as-is
    return head + tail


def _remove_path(path: str, *, best_effort: bool = False) -> None:
    """Remove a file or directory at ``path``, whichever it is.

    Precondition: ``path`` exists. Postcondition: ``path`` no longer
    exists (or, with ``best_effort=True``, removal was attempted and any
    ``OSError`` was swallowed — used for cleanup that must never mask
    the caller's own in-flight exception).
    """
    if best_effort:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            with contextlib.suppress(OSError):
                os.remove(path)
        return
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    else:
        os.remove(path)


def commit_entry(tmp_dir: str, deps_dir: str, entry: str) -> str | None:
    """Move one top-level ``tmp_dir`` entry into ``deps_dir``.

    Precondition: ``entry`` is a direct child name of both ``tmp_dir``
    (must exist there) and, if present, ``deps_dir``.
    Postcondition: returns ``None`` on success (dest now holds the new
    entry, any pre-existing dest was moved to a same-directory backup
    which is then removed) or the backup path on FAILURE, in which case
    dest has been restored to its PRE-CALL state (rollback) and the
    caller is responsible for NOT deleting ``tmp_dir`` so ``entry``'s
    freshly-downloaded copy survives for a retry.

    Non-destructive by construction (issue #97 suggestion 2): the
    previous version's ``rmtree(dest)`` before ``os.replace`` meant a
    mid-loop failure left dest permanently deleted with nothing to
    restore. Renaming dest aside first means the ORIGINAL bytes are
    still on disk until the replace has actually succeeded.
    """
    dest = os.path.join(deps_dir, entry)
    src = os.path.join(tmp_dir, entry)
    backup = f"{dest}.bak-{os.getpid()}"
    had_dest = os.path.exists(dest)
    if had_dest:
        if os.path.exists(backup):
            _remove_path(backup, best_effort=True)
        os.replace(dest, backup)
    try:
        os.replace(src, dest)
    except OSError:
        if had_dest:
            # Restore the pre-call state; leave `backup` for the caller's
            # rollback bookkeeping (removed once restore is confirmed).
            if os.path.exists(dest):
                _remove_path(dest, best_effort=True)
            os.replace(backup, dest)
        raise
    if had_dest:
        _remove_path(backup, best_effort=True)
    return None


def _entry_already_satisfied(
    entry: str, tmp_versions: dict[str, str], dest_versions: dict[str, str]
) -> bool:
    """Idempotence guard (issue #97 suggestion 1): true iff ``dest``
    already has the exact version ``tmp_dir`` resolved for ``entry`` --
    protects a locked, already-correct transitive dep (e.g. numpy under
    a running MCP server) from ever entering the rmtree/replace path."""
    key = _fs.entry_dist_key(entry)
    tmp_v = tmp_versions.get(key)
    return tmp_v is not None and dest_versions.get(key) == tmp_v


def _commit_resolved_entries(tmp_dir: str, deps_dir: str) -> tuple[bool, str | None]:
    """Commit every top-level ``tmp_dir`` entry into ``deps_dir``.

    Precondition: ``tmp_dir`` holds a completed, successful pip
    ``--target`` install. Postcondition: ``(True, None)`` iff every
    entry committed (or was already satisfied) and every stale
    ``*.dist-info`` sibling has been pruned; ``(False, failed_entry)`` on
    the first commit failure, with NO dist-info pruned and ``deps_dir``
    restored for every entry processed so far.

    Issue #149: ``os.listdir`` order is unspecified by the stdlib and
    differs by OS/filesystem; a single distribution spans two entries
    here (its ``.dist-info`` and its package directory), and the batch
    is only atomic at the whole-``tmp_dir`` level (stops at the first
    failure). Pruning the OLD dist-info per-entry, immediately after ITS
    OWN commit, let an ordering where the dist-info committed before the
    package directory delete the still-valid old metadata and then hit
    the package-directory failure/rollback -- so the prune below now
    waits for the whole batch to confirm success.
    """
    tmp_versions = _fs.dist_info_versions(tmp_dir)
    dest_versions = _fs.dist_info_versions(deps_dir)
    committed_dist_infos: list[str] = []
    for entry in os.listdir(tmp_dir):
        if _entry_already_satisfied(entry, tmp_versions, dest_versions):
            continue
        try:
            commit_entry(tmp_dir, deps_dir, entry)
        except OSError as exc:
            print(
                f"[cortex-launcher] commit failed for {entry}: {exc}. "
                f"Rolled back; retry preserved at {tmp_dir}.",
                file=sys.stderr,
            )
            return False, entry
        if entry.endswith(".dist-info"):
            committed_dist_infos.append(entry)
    # Residue 2: only reached once the WHOLE tmp_dir has committed.
    for entry in committed_dist_infos:
        _fs.prune_superseded_dist_info(deps_dir, entry)
    return True, None


def _cleanup_scratch(tmp_dir: str) -> None:
    try:
        shutil.rmtree(tmp_dir)
    except FileNotFoundError:
        return  # A download failure can precede creation of the install target.
    except OSError as exc:
        print(f"[cortex-launcher] scratch cleanup failed: {exc}", file=sys.stderr)


def _report_failure(process: subprocess.CompletedProcess[str]) -> None:
    error = (process.stderr or "") + (process.stdout or "")
    print(
        f"[cortex-launcher] dependency install failed:\n"
        f"{error.strip()[-_PIP_ERROR_TAIL_CHARS:]}",
        file=sys.stderr,
    )


def pip_install(
    deps_dir: str, packages: list[str], constraints: list[str] | None = None
) -> bool:
    """Resolve into scratch, then retain the existing per-entry rollback policy.

    Linux ML resolves a hash-checked CPU torch wheel even for partial installs.
    A failed commit preserves scratch entries for recovery; no success stamp is
    allowed by the caller when this function returns False.
    """
    tmp_dir = f"{deps_dir}.tmp-{os.getpid()}"
    normalized = [constraint_without_extras(spec) for spec in constraints or []]
    try:
        process = _pip.resolve(deps_dir, packages, normalized)
    except (OSError, _cpu.CpuWheelError) as exc:
        print(
            f"[cortex-launcher] dependency resolution failed: "
            f"{str(exc)[-_PIP_ERROR_TAIL_CHARS:]}",
            file=sys.stderr,
        )
        _cleanup_scratch(tmp_dir)
        return False
    if process.returncode:
        _report_failure(process)
        _cleanup_scratch(tmp_dir)
        return False
    ok, failed_entry = _commit_resolved_entries(tmp_dir, deps_dir)
    if ok:
        _cleanup_scratch(tmp_dir)
    else:
        print(
            f"[cortex-launcher] dependency commit stopped at {failed_entry}; "
            f"{tmp_dir} preserved for manual recovery or retry.",
            file=sys.stderr,
        )
    return ok
