"""Resolve commit answers against the corpus repository (issue #343, slice 2).

``git_commit_resolver`` turns a hex abbreviation into the one commit it names
in the corpus, consulting object names only (never refs or replace refs) and
refusing a corpus path that is not a repository root. ``check_commit_keys``
confirms, before a run, that every commit key names a commit of that corpus,
so a typo or a hash from another repository fails the run instead of scoring
every answer incorrect.

The resolver reads whatever repository it is given. The two-arm runner
(slice 4) must hand it a read-only copy taken before the agent runs, or an
agent with write access could prune or add objects and change which short
prefixes are ambiguous (it still cannot make a non-prefix of the key pass).

source: issue #343"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable
from pathlib import Path

from benchmarks.outcome.answer_key import (
    _HEX,
    FAMILY_COMMIT,
    CommitResolver,
    OutcomeTask,
)


def _git(repo: Path, args: list[str], stdin: str | None = None) -> str:
    """Run git on ``repo`` only; any git failure raises (never scored).

    ``GIT_*`` variables are dropped so an inherited ``GIT_DIR`` or
    ``GIT_OBJECT_DIRECTORY`` cannot point the lookup at another store, and
    ``--no-replace-objects`` stops ``refs/replace/*`` from changing the type
    or identity git reports for an object.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        ["git", "--no-replace-objects", "-C", str(repo), *args],
        input=stdin,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def git_commit_resolver(repo: Path) -> CommitResolver:
    """Resolve a hex abbreviation to the full commit hash in ``repo``.

    Only object names are consulted, never refs: a branch or tag that happens
    to be spelled in hex cannot stand in for a hash prefix. ``None`` when the
    prefix names no commit or more than one (git lists no candidate below its
    minimum abbreviation, so a too-short prefix is unknown, not ambiguous).
    A broken corpus must stop the run, not score every answer incorrect: a
    path that is not inside a readable repository raises
    ``CalledProcessError``, and a path that is inside one without being its
    work-tree root (a plain subdirectory, a checkout whose ``.git`` is gone)
    raises ``ValueError`` here, before any answer is resolved, instead of
    silently resolving against the enclosing repository. A non-hex name
    passed to the returned function raises ``ValueError``.
    """
    top = Path(_git(repo, ["rev-parse", "--show-toplevel"]).strip())
    if top.resolve() != Path(repo).resolve():
        raise ValueError(f"{repo} is not the root of a git work tree (found {top})")

    def resolve(hex_name: str) -> str | None:
        if not _HEX.fullmatch(hex_name):
            raise ValueError(f"not a hex object name: {hex_name!r}")
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


def check_commit_keys(tasks: Iterable[OutcomeTask], resolve: CommitResolver) -> None:
    """Raise ``ValueError`` unless every commit key names a commit in the corpus."""
    for task in tasks:
        if (
            task.family == FAMILY_COMMIT
            and resolve(task.key["commit"]) != task.key["commit"]
        ):
            raise ValueError(
                f"task {task.task_id!r}: key.commit {task.key['commit']} is not a "
                f"commit of the corpus repository"
            )
