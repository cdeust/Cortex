"""Two-arm runner of the outcome benchmark (issue #343, slice 4).

Runs every task under both arms — ``recall`` and ``no_recall`` — with the
same model, the same effort level, the same task set and the same ordering
(issue #343, step 3), scores each answer on outcome against the answer key
(step 4), and returns the ``TrialOutcome`` list ``paired_delta.summarize``
pairs and scores (step 5).

The verifier reads a snapshot of the corpus, never the corpus itself:
``snapshot_corpus`` makes a self-contained bare clone (``git clone --bare
--no-local --no-hardlinks``, the copy the ``commit_resolver`` docstring
requires) before the first trial, checks that it holds the pin, and removes
its write permission bits. The permission bits are a guard, not a guarantee:
a process running as root ignores them, and the owner can set them again.
The guarantee is that the snapshot
is taken before any agent runs and that its path is never given to the
agent. ``run_two_arms`` then checks every commit key against that snapshot
before the first trial, so a key the corpus does not contain fails the run
instead of scoring every answer incorrect.

The agent is injected: ``Agent`` is any callable that runs one task under
one arm as one independent session and reports the answer, the turns and
tokens it spent, and the model and effort level that actually served it. A
trial served by another model or effort than the ``RunSpec`` (a fallback,
a silent downgrade) raises ``ValueError``: the issue requires the same
model and effort in both arms, and dropping the trial would unpair it.

Order: repeat ``r`` is one sweep; within it the ``recall`` arm runs the
whole task set in the given order, then the ``no_recall`` arm runs the same
task set in the same order. Each trial is an independent session, so the
arm order carries nothing from one arm to the other.

The real agent driver (a Claude session, the recall wiring and the memory
snapshot of the ``recall`` arm) is slice 5.

source: issue #343"""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from benchmarks.outcome.answer_key import OutcomeTask, verify
from benchmarks.outcome.commit_resolver import (
    _git,
    check_commit_keys,
    git_commit_resolver,
)
from benchmarks.outcome.paired_delta import ARM_NO_RECALL, ARM_RECALL, TrialOutcome

# source: issue #343, step 3 — both arms over the same task set in the same
# order; recall first is a labelling choice, each trial being independent
ARM_ORDER = (ARM_RECALL, ARM_NO_RECALL)

# source: stat(2) — every write bit, for owner, group and others
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


def _non_empty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class RunSpec:
    """What both arms share: the model, the effort level, the repeat count."""

    model: str
    effort: str
    repeats: int

    def __post_init__(self) -> None:
        if not _non_empty(self.model) or not _non_empty(self.effort):
            raise ValueError(f"model and effort must be non-empty: {self!r}")
        if (
            not isinstance(self.repeats, int)
            or isinstance(self.repeats, bool)
            or self.repeats < 1
        ):
            raise ValueError(f"repeats must be a positive int: {self.repeats!r}")


@dataclass(frozen=True)
class AgentResult:
    """One session's answer, its cost, and what served it."""

    answer: Mapping[str, object]
    turns: int
    tokens: int
    model: str
    effort: str


class Agent(Protocol):
    def __call__(self, task: OutcomeTask, arm: str, spec: RunSpec) -> AgentResult:
        """Run ``task`` under ``arm`` as one independent session."""
        ...


def _make_read_only(root: Path) -> None:
    for current, dirs, files in os.walk(root):
        for name in files + dirs:
            path = Path(current, name)
            path.chmod(path.stat().st_mode & ~_WRITE_BITS)
    root.chmod(root.stat().st_mode & ~_WRITE_BITS)


def snapshot_corpus(source: Path, destination: Path, pin: str) -> Path:
    """A read-only bare clone of ``source`` at ``destination`` that holds ``pin``.

    ``destination`` must not exist yet. A ``source`` git cannot clone, or a
    clone that lacks ``pin``, raises ``RuntimeError`` with git's message; a
    clone that lacks ``pin`` is removed first. Relative paths are read from
    the caller's working directory.
    """
    # Absolute before git runs in ``destination.parent`` (``git -C``), so a
    # relative ``source`` or ``destination`` keeps naming the caller's path.
    source = Path(source).absolute()
    destination = Path(destination).absolute()
    if destination.exists():
        raise ValueError(f"snapshot destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _git(
        destination.parent,
        [
            "clone",
            "--bare",
            "--no-local",
            "--no-hardlinks",
            "-q",
            "--",
            str(source),
            str(destination),
        ],
    )
    try:
        _git(destination, ["cat-file", "-e", f"{pin}^{{commit}}"])
    except RuntimeError:
        # A snapshot without the pin is unusable; leave no writable clone.
        shutil.rmtree(destination)
        raise
    _make_read_only(destination)
    return destination


def _check_served(
    result: AgentResult, spec: RunSpec, task: OutcomeTask, arm: str
) -> None:
    if not isinstance(result, AgentResult):
        raise ValueError(f"task {task.task_id!r} ({arm}): agent returned {result!r}")
    if (result.model, result.effort) != (spec.model, spec.effort):
        raise ValueError(
            f"task {task.task_id!r} ({arm}): served by {result.model!r} at effort "
            f"{result.effort!r}, the run requires {spec.model!r} at {spec.effort!r}"
        )


def run_two_arms(
    tasks: Sequence[OutcomeTask], agent: Agent, spec: RunSpec, snapshot: Path
) -> tuple[TrialOutcome, ...]:
    """Every task under both arms for ``spec.repeats`` sweeps, scored on outcome.

    ``snapshot`` is the copy ``snapshot_corpus`` made; every commit key is
    checked against it before the first trial.
    """
    if not isinstance(tasks, Sequence) or not tasks:
        raise ValueError("tasks must be a non-empty sequence")
    resolve = git_commit_resolver(snapshot)
    check_commit_keys(tasks, resolve)
    trials = []
    for repeat in range(spec.repeats):
        for arm in ARM_ORDER:
            for task in tasks:
                result = agent(task, arm, spec)
                _check_served(result, spec, task, arm)
                correct = verify(task, result.answer, resolve_commit=resolve)
                trials.append(
                    TrialOutcome(
                        task.task_id, arm, repeat, correct, result.turns, result.tokens
                    )
                )
    return tuple(trials)
