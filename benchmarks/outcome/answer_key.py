"""Task definitions and a Cortex-independent answer verifier (issue #343, slice 2).

The outcome benchmark scores an agent's final answer against an answer key
that is checkable without Cortex (issue #343, step 2). The issue names three
task families; each has its own key and its own answer fields:

- ``introducing_commit`` — "which commit introduced behaviour X". Key: the
  full commit hash. Answer field ``commit``: a hex string. It is correct when
  the corpus repository resolves it to exactly that commit, so any
  unambiguous abbreviation counts and an ambiguous one does not; the
  repository, not a tuned prefix length, decides.
- ``abandoned_approach`` — "was approach Y tried, and what was the recorded
  reason it stopped". Key: ``tried`` and, when tried, the accepted wordings
  of the recorded reason. Answer fields ``tried`` (bool) and ``reason``.
- ``decided_value`` — "what is the decided value of constant Z and its
  cited source". Key: the accepted spellings of the value and the source
  file path(s). Answer fields ``value`` and ``source``; a ``:<line>`` suffix
  on the source is ignored because line numbers drift between commits while
  the file that holds the citation does not.

Free text is compared by exact match after normalisation (Unicode NFKC,
case folding, whitespace collapsed) against the accepted list written in the
task definition. There is no similarity score and no threshold: the issue
forbids tuned constants in the rubric, so a wording the key does not list is
incorrect and the remedy is to extend the key, not to loosen the match.

A malformed task definition raises ``ValueError``. A missing or wrongly
typed answer field is an incorrect answer, not an error: the agent produced
it, and the benchmark scores it.

source: issue #343"""

from __future__ import annotations

import json
import re
import subprocess
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

FAMILY_COMMIT = "introducing_commit"
FAMILY_APPROACH = "abandoned_approach"
FAMILY_VALUE = "decided_value"
FAMILIES = (FAMILY_COMMIT, FAMILY_APPROACH, FAMILY_VALUE)

# source: git hash-function-transition design doc — a full object name is
# 40 hex digits under SHA-1 and 64 under SHA-256
_FULL_HASH_LENGTHS = (40, 64)

_HEX = re.compile(r"[0-9a-f]+")
_LINE_SUFFIX = re.compile(r":\d+$")

CommitResolver = Callable[[str], "str | None"]


def normalize_text(text: str) -> str:
    """NFKC, case-folded, whitespace collapsed to single spaces."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def normalize_source(path: str) -> str:
    """Repository-relative POSIX path, without ``./`` or a ``:<line>`` suffix."""
    stripped = _LINE_SUFFIX.sub("", path.strip()).replace("\\", "/")
    return str(PurePosixPath(stripped))


def _accepted(values: object, field: str, task_id: str) -> frozenset[str]:
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError(f"task {task_id!r}: {field} must be a non-empty list")
    if not all(isinstance(v, str) and v.strip() for v in values):
        raise ValueError(f"task {task_id!r}: {field} entries must be non-empty strings")
    return frozenset(values)


@dataclass(frozen=True)
class OutcomeTask:
    task_id: str
    family: str
    question: str
    key: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id:
            raise ValueError(f"task_id must be a non-empty string: {self.task_id!r}")
        if self.family not in FAMILIES:
            raise ValueError(f"task {self.task_id!r}: unknown family {self.family!r}")
        if not isinstance(self.question, str) or not self.question.strip():
            raise ValueError(f"task {self.task_id!r}: question must be non-empty")
        _KEY_CHECKS[self.family](self.task_id, self.key)


def _check_commit_key(task_id: str, key: Mapping[str, object]) -> None:
    commit = key.get("commit")
    if (
        not isinstance(commit, str)
        or not _HEX.fullmatch(commit)
        or len(commit) not in _FULL_HASH_LENGTHS
    ):
        raise ValueError(
            f"task {task_id!r}: key.commit must be a full lowercase hex hash"
        )


def _check_approach_key(task_id: str, key: Mapping[str, object]) -> None:
    tried = key.get("tried")
    if not isinstance(tried, bool):
        raise ValueError(f"task {task_id!r}: key.tried must be a bool")
    if tried:
        _accepted(key.get("reasons"), "key.reasons", task_id)
    elif "reasons" in key:
        raise ValueError(f"task {task_id!r}: an untried approach has no reasons")


def _check_value_key(task_id: str, key: Mapping[str, object]) -> None:
    _accepted(key.get("values"), "key.values", task_id)
    _accepted(key.get("sources"), "key.sources", task_id)


_KEY_CHECKS = {
    FAMILY_COMMIT: _check_commit_key,
    FAMILY_APPROACH: _check_approach_key,
    FAMILY_VALUE: _check_value_key,
}


def _task_from_json(path: Path, item: object) -> OutcomeTask:
    if not isinstance(item, dict) or not isinstance(item.get("key"), dict):
        raise ValueError(f"{path}: each task must be an object with a 'key' object")
    return OutcomeTask(
        task_id=item.get("id"),
        family=item.get("family"),
        question=item.get("question"),
        key=item["key"],
    )


def load_tasks(path: Path) -> tuple[OutcomeTask, ...]:
    """Read a JSON list of task objects; ids must be unique."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{path}: expected a non-empty JSON list of tasks")
    tasks = tuple(_task_from_json(path, item) for item in raw)
    ids = [t.task_id for t in tasks]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"{path}: duplicate task ids {duplicates}")
    return tasks


def _text_field(answer: Mapping[str, object], name: str) -> str | None:
    value = answer.get(name)
    return value if isinstance(value, str) and value.strip() else None


def _verify_commit(
    task: OutcomeTask, answer: Mapping[str, object], resolve: CommitResolver
) -> bool:
    given = _text_field(answer, "commit")
    if given is None:
        return False
    given = given.strip().lower()
    # Hex only: nothing else reaches the resolver, so no ref name, revision
    # expression or option can stand in for an object name.
    if not _HEX.fullmatch(given):
        return False
    return resolve(given) == task.key["commit"]


def _verify_approach(task: OutcomeTask, answer: Mapping[str, object]) -> bool:
    tried = answer.get("tried")
    if not isinstance(tried, bool) or tried != task.key["tried"]:
        return False
    if not tried:
        return True
    reason = _text_field(answer, "reason")
    accepted = {normalize_text(r) for r in task.key["reasons"]}
    return reason is not None and normalize_text(reason) in accepted


def _verify_value(task: OutcomeTask, answer: Mapping[str, object]) -> bool:
    value = _text_field(answer, "value")
    source = _text_field(answer, "source")
    if value is None or source is None:
        return False
    values = {normalize_text(v) for v in task.key["values"]}
    sources = {normalize_source(s) for s in task.key["sources"]}
    return normalize_text(value) in values and normalize_source(source) in sources


def verify(
    task: OutcomeTask,
    answer: Mapping[str, object],
    *,
    resolve_commit: CommitResolver,
) -> bool:
    """True when ``answer`` matches ``task``'s key; never consults Cortex."""
    if not isinstance(answer, Mapping):
        return False
    if task.family == FAMILY_COMMIT:
        return _verify_commit(task, answer, resolve_commit)
    if task.family == FAMILY_APPROACH:
        return _verify_approach(task, answer)
    return _verify_value(task, answer)


def git_commit_resolver(repo: Path) -> CommitResolver:
    """Resolve a hex abbreviation to the full commit hash in ``repo``.

    ``None`` when git cannot name exactly one commit (unknown or ambiguous).
    """

    def resolve(hex_name: str) -> str | None:
        if not _HEX.fullmatch(hex_name):
            raise ValueError(f"not a hex object name: {hex_name!r}")
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "rev-parse",
                "--verify",
                "--quiet",
                f"{hex_name}^{{commit}}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    return resolve
