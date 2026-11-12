"""Outcome benchmark corpus and the evidence of its tasks (issue #343, slice 3).

The corpus is the history of this repository, pinned at ``CORPUS_PIN``
(decision on issue #343, 2026-11-12: the issue asks for "a repo with genuine
Cortex history rather than a seeded one"). ``cortex_tasks.json`` holds tasks
of the three families of ``answer_key``, drawn from that history.

Each task carries an ``evidence`` object, which ``load_tasks`` ignores and
``check_evidence`` verifies against the pinned commit, so a key cannot drift
from the history it claims to come from:

- ``introducing_commit``: ``added_path``. The key must be the oldest commit
  reachable from the pin that adds that path.
- ``abandoned_approach``: ``commit``. That commit must be reachable from the
  pin, and its message must contain the first accepted reason of the key.
  An approach that was never tried has no commit to point to, so the corpus
  holds tried approaches only.
- ``decided_value``: ``quotes``, one quotation per key source. Each quotation
  must appear in that file at the pin and contain the first accepted value.

Text is compared after ``normalize_text``, so a line break in a commit
message does not matter. The repository given to ``check_evidence`` is the
same self-contained snapshot the resolver reads (see ``commit_resolver``).

source: issue #343"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from benchmarks.outcome.answer_key import (
    FAMILY_APPROACH,
    FAMILY_COMMIT,
    OutcomeTask,
    load_tasks,
    normalize_text,
)
from benchmarks.outcome.commit_resolver import _git

# source: issue #343, decision comment of 2026-11-12 — cdeust/Cortex is the corpus
CORPUS_REPOSITORY = "https://github.com/cdeust/Cortex.git"
# source: issue #343, decision comment of 2026-11-12 — head of main on that day
CORPUS_PIN = "5205f6313601ca93057ec2f271afca92ee08938d"
# source: issue #343, slice 3 — the task set lives beside this module
TASKS_PATH = Path(__file__).with_name("cortex_tasks.json")


def load_corpus_tasks(path: Path = TASKS_PATH) -> tuple[OutcomeTask, ...]:
    """The tasks of the corpus, validated by ``answer_key.load_tasks``."""
    return load_tasks(path)


def _raw_evidence(path: Path) -> dict[str, Mapping[str, object]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    evidence = {}
    for item in raw:
        found = item.get("evidence")
        if not isinstance(found, dict):
            raise ValueError(f"task {item.get('id')!r}: missing evidence object")
        evidence[item["id"]] = found
    return evidence


def _is_ancestor(repo: Path, commit: str, pin: str) -> bool:
    try:
        _git(repo, ["merge-base", "--is-ancestor", commit, pin])
    except RuntimeError:
        return False
    return True


def _check_commit(repo: Path, pin: str, task: OutcomeTask, ev: Mapping) -> str | None:
    path = ev.get("added_path")
    if not isinstance(path, str) or not path:
        return "evidence.added_path must be a path"
    adds = _git(repo, ["log", "--diff-filter=A", "--format=%H", pin, "--", path])
    oldest = adds.split()[-1] if adds.split() else None
    if oldest != task.key["commit"]:
        return f"{path} was first added by {oldest}, not by the key commit"
    return None


def _check_approach(repo: Path, pin: str, task: OutcomeTask, ev: Mapping) -> str | None:
    commit = ev.get("commit")
    if not isinstance(commit, str) or not _is_ancestor(repo, commit, pin):
        return f"evidence.commit {commit!r} is not a commit reachable from the pin"
    message = normalize_text(_git(repo, ["log", "-1", "--format=%B", commit]))
    if not task.key["tried"] or normalize_text(task.key["reasons"][0]) not in message:
        return f"the message of {commit} does not record the first accepted reason"
    return None


def _check_value(repo: Path, pin: str, task: OutcomeTask, ev: Mapping) -> str | None:
    quotes = ev.get("quotes")
    if not isinstance(quotes, dict) or set(quotes) != set(task.key["sources"]):
        return "evidence.quotes must quote every key source, and only those"
    value = normalize_text(task.key["values"][0])
    for source, quote in quotes.items():
        text = normalize_text(_git(repo, ["show", f"{pin}:{source}"]))
        if not isinstance(quote, str) or value not in normalize_text(quote):
            return f"the quotation of {source} does not contain {value!r}"
        if normalize_text(quote) not in text:
            return f"{source} at the pin does not contain its quotation"
    return None


def evidence_problems(
    tasks: Sequence[OutcomeTask],
    evidence: Mapping[str, Mapping[str, object]],
    repo: Path,
    pin: str,
) -> list[str]:
    """One line per task whose evidence the pinned history does not support."""
    problems = []
    for task in tasks:
        if task.family == FAMILY_COMMIT:
            check = _check_commit
        elif task.family == FAMILY_APPROACH:
            check = _check_approach
        else:
            check = _check_value
        problem = check(repo, pin, task, evidence[task.task_id])
        if problem is not None:
            problems.append(f"task {task.task_id!r}: {problem}")
    return problems


def check_evidence(repo: Path, pin: str = CORPUS_PIN, path: Path = TASKS_PATH) -> None:
    """Raise ``ValueError`` unless every task of ``path`` is backed by ``pin``.

    ``repo`` must contain the pin: a shallow snapshot that lacks it raises
    ``RuntimeError`` (git's message), instead of reporting every task as
    unsupported.
    """
    _git(repo, ["cat-file", "-e", f"{pin}^{{commit}}"])
    problems = evidence_problems(load_tasks(path), _raw_evidence(path), repo, pin)
    if problems:
        raise ValueError("\n".join(problems))
