"""Resolve commit answers against the corpus repository (issue #343, slice 2).

``git_commit_resolver`` turns a hex abbreviation into the one commit it names
in the corpus, consulting object names only (never refs or replace refs) and
refusing a corpus path that is not a repository root. ``check_commit_keys``
confirms, before a run, that every commit key names a commit of that corpus,
so a typo or a hash from another repository fails the run instead of scoring
every answer incorrect.

The corpus must be self-contained: a work tree with its own ``.git``
directory, or a bare repository, whose object store is not borrowed through
``objects/info/alternates``, a ``gitdir:`` file or ``commondir``. Anything
else raises before an answer is scored, because those indirections would
read an object store outside the snapshot.

The resolver reads whatever repository it is given. The two-arm runner
(slice 4) must hand it a read-only, self-contained copy taken before the
agent runs, made with ``git clone --bare``/``--mirror`` or ``git clone
--no-local --no-hardlinks``, and must call ``check_commit_keys`` on that
same copy before the first trial: an agent with write access could
otherwise prune or add objects and change which short prefixes are
ambiguous (it still cannot make a non-prefix of the key pass). A ``cp -r``
of a work tree's ``.git`` keeps ``core.bare=false`` and is rejected, and so
is a ``.git`` that is a symlink or any symlink under ``objects/``; that walk
is a guard, the fresh clone is the guarantee.

Environment: git 2.32 or newer is required and checked; a missing ``git``
binary raises ``FileNotFoundError``. Git reads no global or system config
and never fetches a missing object lazily (``GIT_NO_LAZY_FETCH``, honoured
from git 2.44). No ``safe.directory`` override can reach it (global, system
and command-line config are all excluded), so the snapshot must belong to
the user running the verifier: git releases with the CVE-2022-24765 fix
refuse anything else as "dubious ownership". The symlink guard is POSIX
only (an NTFS junction is not a symlink to ``os.walk``). Shallow and
partial clones pass the corpus check; ``check_commit_keys`` still rejects a
key commit the snapshot does not contain.

source: issue #343"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Sequence
from typing import NoReturn
from pathlib import Path

from benchmarks.outcome.answer_key import FAMILY_COMMIT, CommitResolver, OutcomeTask

_LOWER_HEX = re.compile(r"[0-9a-f]+")

# source: git release notes — `rev-parse --path-format` arrived in 2.31.0 and
# `GIT_CONFIG_GLOBAL` in 2.32.0; older git silently echoes or ignores them.
_MIN_GIT = (2, 32)

# Git reads no global or system config, so CI and developer machines resolve
# identically (repository-local config still applies), and, from git 2.44,
# never runs a promisor fetch for an object it does not have.
_ISOLATED_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_NO_LAZY_FETCH": "1",
}


def _git(repo: Path, args: list[str], stdin: str | None = None) -> str:
    """Run git on ``repo`` only; a git failure raises ``RuntimeError``.

    ``GIT_*`` variables are dropped so an inherited ``GIT_DIR`` or
    ``GIT_OBJECT_DIRECTORY`` cannot point the lookup at another store, and
    ``--no-replace-objects`` stops ``refs/replace/*`` from changing the type
    or identity git reports for an object. Git's stderr is kept in the error.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        return subprocess.run(
            ["git", "--no-replace-objects", "-C", str(repo), *args],
            input=stdin,
            env={**env, **_ISOLATED_ENV},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {repo}: {error.stderr.strip()}"
        ) from error


def _check_git_version() -> None:
    try:
        out = subprocess.run(
            ["git", "version"], capture_output=True, text=True, check=True
        ).stdout
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"git version failed: {error.stderr.strip()}") from error
    match = re.search(r"(\d+)\.(\d+)", out)
    if match is None or (int(match[1]), int(match[2])) < _MIN_GIT:
        raise RuntimeError(
            f"git >= {_MIN_GIT[0]}.{_MIN_GIT[1]} required, found {out!r}"
        )


def _same_path(found: str, expected: Path) -> bool:
    return (
        expected.exists()
        and os.path.exists(found)
        and os.path.samefile(found, expected)
    )


def _uninspectable(error: OSError) -> NoReturn:
    raise ValueError(f"cannot inspect {error.filename}: {error}") from error


def _reject_symlinks(repo: Path, git_dir: Path) -> None:
    """Any symlink at ``.git`` or under ``objects/`` could point anywhere.

    A directory the walk cannot list raises instead of being skipped.
    """
    if (repo / ".git").is_symlink() or (git_dir / "objects").is_symlink():
        raise ValueError(f"{repo}: .git or objects/ is a symlink")
    for root, dirs, files in os.walk(git_dir / "objects", onerror=_uninspectable):
        for name in dirs + files:
            if os.path.islink(os.path.join(root, name)):
                raise ValueError(f"{repo}: {os.path.join(root, name)} is a symlink")


def _check_corpus(repo: Path) -> None:
    """Raise unless ``repo`` is a self-contained repository root."""
    info = _git(
        repo,
        [
            "rev-parse",
            "--path-format=absolute",
            "--is-bare-repository",
            "--absolute-git-dir",
            "--git-common-dir",
        ],
    ).splitlines()
    try:
        bare, git_dir, common_dir = info  # one line per requested field
    except ValueError as error:
        raise ValueError(f"{repo}: unexpected rev-parse output {info!r}") from error
    expected = repo if bare == "true" else repo / ".git"
    if not _same_path(git_dir, expected):
        raise ValueError(
            f"{repo} is not a self-contained repository root (git dir {git_dir})"
        )
    if not _same_path(common_dir, expected):
        raise ValueError(
            f"{repo} is not a self-contained repository root (common dir {common_dir})"
        )
    # After the root checks, so ``objects/`` is known to exist; `samefile`
    # follows links, so only this walk catches a symlinked store.
    _reject_symlinks(repo, expected)
    if (expected / "objects" / "info" / "alternates").exists():
        raise ValueError(f"{repo} borrows objects through objects/info/alternates")


def git_commit_resolver(repo: Path) -> CommitResolver:
    """Resolve a lowercase hex abbreviation to the full commit hash in ``repo``.

    Only object names are consulted, never refs: a branch or tag that happens
    to be spelled in hex cannot stand in for a hash prefix. ``None`` when the
    prefix names no commit or more than one (git lists no candidate below its
    hard minimum of 4 hex digits, or beyond the repository's hash length).

    A broken corpus stops the run instead of scoring every answer incorrect.
    Before any answer is resolved, a path git cannot open raises
    ``RuntimeError`` (with git's message), and a path that is not a
    self-contained repository root (see the module docstring), a directory
    under ``objects/`` the walk cannot list or unexpected ``rev-parse`` output raises
    ``ValueError``; git older than 2.32 raises ``RuntimeError``, and a
    missing ``git`` binary ``FileNotFoundError``. The returned
    function raises ``ValueError`` for a name that is not lowercase hex
    (``verify`` lowercases answers first) and ``RuntimeError`` if git fails
    mid-run.
    """
    _check_git_version()
    repo = Path(repo)
    _check_corpus(repo)

    def resolve(hex_name: str) -> str | None:
        if not _LOWER_HEX.fullmatch(hex_name):
            raise ValueError(f"not a lowercase hex object name: {hex_name!r}")
        candidates = _git(repo, ["rev-parse", f"--disambiguate={hex_name}"])
        if not candidates.strip():
            return None
        typed = _git(
            repo, ["cat-file", "--batch-check=%(objectname) %(objecttype)"], candidates
        )
        commits = [
            name
            for name, kind in (line.split() for line in typed.splitlines())
            if kind == "commit"
        ]
        return commits[0] if len(commits) == 1 else None

    return resolve


def check_commit_keys(tasks: Sequence[OutcomeTask], resolve: CommitResolver) -> None:
    """Raise ``ValueError`` unless every commit key names a commit in the corpus.

    A ``Sequence``, not an iterable: the runner iterates the same tasks again
    to run the trials, and a consumed generator would score zero tasks.
    """
    for task in tasks:
        if (
            task.family == FAMILY_COMMIT
            and resolve(task.key["commit"]) != task.key["commit"]
        ):
            raise ValueError(
                f"task {task.task_id!r}: key.commit {task.key['commit']} is not a "
                f"commit of the corpus repository"
            )
