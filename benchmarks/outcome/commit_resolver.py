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
agent runs (``git clone --no-local --no-hardlinks``, or a bare mirror), and
must call ``check_commit_keys`` on that same copy before the first trial:
an agent with write access could otherwise prune or add objects and change
which short prefixes are ambiguous (it still cannot make a non-prefix of
the key pass).

source: issue #343"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path

from benchmarks.outcome.answer_key import FAMILY_COMMIT, CommitResolver, OutcomeTask

_LOWER_HEX = re.compile(r"[0-9a-f]+")

# Git reads no global or system config, so CI and developer machines resolve
# identically; repository-local config still applies.
_ISOLATED_CONFIG = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


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
            env={**env, **_ISOLATED_CONFIG},
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {repo}: {error.stderr.strip()}"
        ) from error


def _same_path(found: str, expected: Path) -> bool:
    return expected.exists() and os.path.samefile(found, expected)


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
    bare, git_dir, common_dir = info[0], info[1], info[2]
    expected = repo if bare == "true" else repo / ".git"
    if not _same_path(git_dir, expected) or not _same_path(common_dir, expected):
        raise ValueError(
            f"{repo} is not a self-contained repository root (git dir {git_dir}, "
            f"common dir {common_dir})"
        )
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
    self-contained repository root (see the module docstring) raises
    ``ValueError``. The returned function raises ``ValueError`` for a name
    that is not lowercase hex (``verify`` lowercases answers first).
    """
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
