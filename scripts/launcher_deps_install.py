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


def _remove_path(path: str, *, best_effort: bool = False) -> None:
    """Remove a file or directory at ``path``, whichever it is.

    Precondition: ``path`` exists. Postcondition: ``path`` no longer
    exists (or, with ``best_effort=True``, removal was attempted and any
    ``OSError`` was swallowed — used for cleanup that must never mask
    the caller's own in-flight exception).
    """
    if best_effort:
        if Path(path).is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            with contextlib.suppress(OSError):
                Path(path).unlink()
        return
    if Path(path).is_dir():
        shutil.rmtree(path, ignore_errors=True)
    else:
        Path(path).unlink()


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
    dest = Path(deps_dir) / entry
    src = Path(tmp_dir) / entry
    backup = f"{dest}.bak-{os.getpid()}"
    had_dest = dest.exists()
    if had_dest:
        if Path(backup).exists():
            _remove_path(backup, best_effort=True)
        dest.replace(backup)
    try:
        src.replace(dest)
    except OSError:
        if had_dest:
            # Restore the pre-call state; leave `backup` for the caller's
            # rollback bookkeeping (removed once restore is confirmed).
            if dest.exists():
                _remove_path(dest, best_effort=True)
            Path(backup).replace(dest)
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
    for entry_path in Path(tmp_dir).iterdir():
        entry = entry_path.name
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


def pip_install(
    deps_dir: str, packages: list[str], constraints: list[str] | None = None
) -> bool:
    """Install ``packages`` into ``deps_dir``, surfacing failures.

    Returns True iff every resolved top-level entry was either already
    satisfied (idempotence guard, issue #97 suggestion 1) or committed
    without error. On any commit failure, ``tmp_dir`` is deliberately
    NOT removed (issue #97 suggestion 2: the old ``finally:
    shutil.rmtree(tmp_dir)`` is exactly what made a failed commit
    unrecoverable — it deleted the freshly-installed replacement too).

    PEP 668 interpreters refuse ``pip install`` with an
    ``externally-managed-environment`` error; the explicit
    user-requested override is ``--break-system-packages``. Installing
    with ``--target`` into the plugin's own deps dir never touches
    system site-packages, so the override is safe here.

    Supply-chain safety: ``--index-url`` pins the official PyPI index;
    the sanitized env below strips any inherited PIP_INDEX_URL /
    PIP_EXTRA_INDEX_URL / PIP_CONFIG_FILE so a caller can't reopen the
    dependency-confusion vector this closes.

    ``constraints``, when given, is a list of pip specs (``name==ver``)
    written to a ``-c`` constraints file for this install only (issue
    #97 residue 3, reporter mbe14, "the substantial one"): without it, a
    package pip pulls in as a TRANSITIVE (e.g. numpy via
    sentence-transformers for the ML install) resolves freely and can
    land on a different version than the pin the base install already
    committed, splitting deps_dir's numpy across two callers. Passing
    the base pins as constraints on the ML install forces pip to solve
    within them, so a shared transitive agrees with the base pin instead
    of "whatever pip's resolver happens to pick this time."

    # source: rules/coding-standards.md §4.2, §10 — this function is
    # ~100 lines, over the 50-line / Medium-stakes-flexed 60-line budget.
    # Pre-existing (137 lines before issue #149's fix; the fix already
    # extracted the commit loop into `_commit_resolved_entries` and cut
    # this by ~30 lines). The remainder is the PEP-668-retry + pip
    # subprocess-invocation concern, unrelated to #149's bug and out of
    # this change's blast radius; further splitting it is deferred to a
    # dedicated structural pass rather than risked inside a flake fix.
    """
    tmp_dir = f"{deps_dir}.tmp-{os.getpid()}"
    clean_env = dict(os.environ)
    for _var in (
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "PIP_CONFIG_FILE",
        "PIP_FIND_LINKS",
        "PIP_TRUSTED_HOST",
    ):
        clean_env.pop(_var, None)
    constraints_file = None
    if constraints:
        constraints_file = f"{deps_dir}.constraints-{os.getpid()}.txt"
        with Path(constraints_file).open("w", encoding="utf-8") as fh:
            fh.write("\n".join(constraints) + "\n")
    base = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "-q",
        "--index-url",
        "https://pypi.org/simple/",
        *(["-c", constraints_file] if constraints_file else []),
        "--target",
        tmp_dir,
        *packages,
    ]
    proc = subprocess.run(base, capture_output=True, text=True, env=clean_env)  # noqa: S603 — base is [sys.executable, "-m", "pip", "install", ...hardcoded flags..., *packages]; packages are this repo's own pinned dependency specs, never external input
    err = (proc.stderr or "") + (proc.stdout or "")
    if proc.returncode != 0 and "externally-managed-environment" in err:
        print(
            "[cortex-launcher] WARNING: pip reports an externally-managed "
            "Python environment (PEP 668). The Cortex plugin installs "
            "dependencies into its own private directory (not system "
            "site-packages), so --break-system-packages is safe here. "
            "Retrying with that flag now. If you want to suppress this "
            f"retry, pre-install the packages yourself: {', '.join(packages)}",
            file=sys.stderr,
        )
        proc = subprocess.run(  # noqa: S603 — same base argv as above (sys.executable -m pip install ...) plus a hardcoded literal flag
            base + ["--break-system-packages"],
            capture_output=True,
            text=True,
            env=clean_env,
        )
        err = (proc.stderr or "") + (proc.stdout or "")
    if constraints_file is not None:
        # Only a resolution hint for THIS pip invocation — not needed
        # past this point regardless of outcome.
        with contextlib.suppress(OSError):
            Path(constraints_file).unlink()
    if proc.returncode != 0:
        print(
            "[cortex-launcher] dependency install failed for "
            f"{', '.join(packages)} (python {sys.executable}).\n"
            f"[cortex-launcher] pip said:\n{err.strip()[-2000:]}\n"
            "[cortex-launcher] Fix the pip failure above (network/proxy/"
            "permissions), or pre-install the packages, then reconnect "
            "the cortex MCP server.",
            file=sys.stderr,
        )
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return False

    ok, failed_entry = _commit_resolved_entries(tmp_dir, deps_dir)
    if ok:
        shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        print(
            f"[cortex-launcher] dependency commit stopped at {failed_entry}; "
            f"{tmp_dir} preserved for manual recovery or retry.",
            file=sys.stderr,
        )
    return ok
