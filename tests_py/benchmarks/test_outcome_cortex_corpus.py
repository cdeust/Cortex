"""The Cortex corpus of the outcome benchmark (issue #343, slice 3).

The task set must load under the slice 2 schema and cover the three
families, every task must carry evidence, and ``evidence_problems`` must
refuse a key that the pinned history does not support. The last test checks
the real task set against a bare snapshot of this repository; it needs the
pinned commit, which a shallow checkout (the hosted Pipeline's default)
does not have."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from benchmarks.outcome.answer_key import FAMILIES, OutcomeTask
from benchmarks.outcome.commit_resolver import check_commit_keys, git_commit_resolver
from benchmarks.outcome.cortex_corpus import (
    CORPUS_PIN,
    TASKS_PATH,
    _raw_evidence,
    check_evidence,
    evidence_problems,
    load_corpus_tasks,
)
from tests_py.benchmarks.outcome_git import git

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_tasks_load_and_cover_the_three_families():
    tasks = load_corpus_tasks()
    assert {t.family for t in tasks} == set(FAMILIES)


def test_every_task_carries_evidence():
    ids = {t.task_id for t in load_corpus_tasks()}
    assert set(_raw_evidence(TASKS_PATH)) == ids


@pytest.fixture
def history(tmp_path):
    repo = tmp_path / "corpus"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a.py").write_text("LIMIT = 7\n", encoding="utf-8")
    git(repo, "add", "a.py")
    git(repo, "commit", "-qm", "add a: the old gate was too slow")
    added = git(repo, "rev-parse", "HEAD")
    (repo / "b.txt").write_text("b", encoding="utf-8")
    git(repo, "add", "b.txt")
    git(repo, "commit", "-qm", "add b")
    return repo, added, git(repo, "rev-parse", "HEAD")


def _commit_task(commit):
    return OutcomeTask("c", "introducing_commit", "q?", {"commit": commit})


def test_commit_key_must_be_the_commit_that_added_the_path(history):
    repo, added, pin = history
    ev = {"c": {"added_path": "a.py"}}
    assert evidence_problems([_commit_task(added)], ev, repo, pin) == []
    assert evidence_problems([_commit_task(pin)], ev, repo, pin) != []


def test_approach_reason_must_be_in_the_commit_message(history):
    repo, added, pin = history

    def task(reason):
        return OutcomeTask(
            "a", "abandoned_approach", "q?", {"tried": True, "reasons": [reason]}
        )

    ev = {"a": {"commit": added}}
    assert evidence_problems([task("The old  gate was too slow")], ev, repo, pin) == []
    assert evidence_problems([task("it was too fast")], ev, repo, pin) != []


def test_value_quote_must_hold_the_value_and_appear_in_the_source(history):
    repo, _, pin = history
    task = OutcomeTask(
        "v", "decided_value", "q?", {"values": ["7"], "sources": ["a.py"]}
    )

    def problems(quotes):
        return evidence_problems([task], {"v": {"quotes": quotes}}, repo, pin)

    assert problems({"a.py": "LIMIT = 7"}) == []
    assert problems({"a.py": "LIMIT = 8"}) != []
    assert problems({"a.py": "LIMIT = 7 # cited"}) != []
    assert problems({}) != []


def test_real_task_set_is_backed_by_the_pinned_history(tmp_path):
    bare = tmp_path / "cortex.git"
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(_REPO_ROOT), str(bare)], check=True
    )
    present = subprocess.run(
        ["git", "-C", str(bare), "cat-file", "-e", f"{CORPUS_PIN}^{{commit}}"],
        capture_output=True,
    )
    if present.returncode != 0:
        pytest.skip(f"checkout lacks the corpus pin {CORPUS_PIN} (shallow clone)")
    check_evidence(bare)
    check_commit_keys(load_corpus_tasks(), git_commit_resolver(bare))
