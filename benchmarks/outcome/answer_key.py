"""Task definitions and a Cortex-independent answer verifier (issue #343, slice 2).

The outcome benchmark scores an agent's final answer against an answer key
that is checkable without Cortex (issue #343, step 2). The issue names three
task families; each has its own key and its own answer fields:

- ``introducing_commit`` — "which commit introduced behaviour X". Key: the
  full commit hash. Answer field ``commit``: a hex string. It is correct when
  it is a prefix of exactly one commit object in the corpus repository and
  that commit is the key. Refs are never consulted, so a branch or tag
  spelled in hex does not count; objects that are not commits (blobs, trees,
  annotated tag objects) neither count nor make a prefix ambiguous; git's own
  minimum abbreviation applies (a shorter prefix names nothing). The
  repository, not a tuned prefix length, decides.
- ``abandoned_approach`` — "was approach Y tried, and what was the recorded
  reason it stopped". Key: ``tried`` and, when tried, the accepted wordings
  of the recorded reason. Answer fields ``tried`` (bool) and ``reason``.
- ``decided_value`` — "what is the decided value of constant Z and its
  cited source". Key: the accepted spellings of the value and the source
  file path(s), repository-relative. Answer fields ``value`` and ``source``;
  one trailing ``:<line>`` on the source is ignored because line numbers
  drift between commits while the file that holds the citation does not.
  Any other spelling (``#L52``, ``:52-60``, an absolute path) is not
  rewritten and does not match.

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
import os
import re
import subprocess
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
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
    """POSIX separators, ``./`` collapsed, one trailing ``:<line>`` removed."""
    stripped = _LINE_SUFFIX.sub("", path.strip()).replace("\\", "/")
    return str(PurePosixPath(stripped))


def _accepted(values: object, field: str, task_id: str) -> frozenset[str]:
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError(f"task {task_id!r}: {field} must be a non-empty list")
    if not all(isinstance(v, str) and v.strip() for v in values):
        raise ValueError(f"task {task_id!r}: {field} entries must be non-empty strings")
    return frozenset(values)


def _check_source(source: str, task_id: str) -> None:
    path = PurePosixPath(normalize_source(source))
    if path.is_absolute() or ".." in path.parts or str(path) == ".":
        raise ValueError(
            f"task {task_id!r}: key source {source!r} must name a file inside the repo"
        )


def _freeze(key: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(
        {k: tuple(v) if isinstance(v, list) else v for k, v in key.items()}
    )


@dataclass(frozen=True)
class OutcomeTask:
    task_id: str
    family: str
    question: str
    key: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not self.task_id.strip():
            raise ValueError(f"task_id must be a non-empty string: {self.task_id!r}")
        if self.family not in FAMILIES:
            raise ValueError(f"task {self.task_id!r}: unknown family {self.family!r}")
        if not isinstance(self.question, str) or not self.question.strip():
            raise ValueError(f"task {self.task_id!r}: question must be non-empty")
        if not isinstance(self.key, Mapping):
            raise ValueError(f"task {self.task_id!r}: key must be a mapping")
        fields, check = _KEY_SCHEMAS[self.family]
        unknown = sorted(set(self.key) - fields)
        if unknown:
            raise ValueError(f"task {self.task_id!r}: unknown key fields {unknown}")
        check(self.task_id, self.key)
        # Frozen after validation, so the checked key is the key that scores.
        object.__setattr__(self, "key", _freeze(self.key))


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
    for source in _accepted(key.get("sources"), "key.sources", task_id):
        _check_source(source, task_id)


_KEY_SCHEMAS = {
    FAMILY_COMMIT: (frozenset({"commit"}), _check_commit_key),
    FAMILY_APPROACH: (frozenset({"tried", "reasons"}), _check_approach_key),
    FAMILY_VALUE: (frozenset({"values", "sources"}), _check_value_key),
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
    # Hex only, so no revision expression or option reaches git; no longer
    # than a full hash, so an oversized answer cannot overflow argv.
    if not _HEX.fullmatch(given) or len(given) > max(_FULL_HASH_LENGTHS):
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


def _git(repo: Path, args: list[str], stdin: str | None = None) -> str:
    """Run git on ``repo`` only; any git failure raises (never scored).

    ``GIT_*`` variables are dropped so an inherited ``GIT_DIR`` or
    ``GIT_OBJECT_DIRECTORY`` cannot point the lookup at another store.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        ["git", "-C", str(repo), *args],
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
    A path that is not a readable repository raises ``CalledProcessError``:
    a broken corpus must stop the run, not score every answer incorrect.
    """

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
