"""Tests for benchmarks/outcome/answer_key.py (issue #343, slice 2).

The commit family is exercised against a real throwaway git repository, so
abbreviation and ambiguity are decided by git, as in a real run."""

from __future__ import annotations

import json
import subprocess

import pytest

from benchmarks.outcome.answer_key import (
    FAMILY_APPROACH,
    FAMILY_COMMIT,
    FAMILY_VALUE,
    OutcomeTask,
    git_commit_resolver,
    load_tasks,
    normalize_source,
    normalize_text,
    verify,
)

_SHA = "0123456789abcdef0123456789abcdef01234567"


def _no_git(_name):
    raise AssertionError("resolver must not be called")


def _value_task():
    return OutcomeTask(
        "z",
        FAMILY_VALUE,
        "Decided value of _CI_ALPHA and its source?",
        {"values": ["0.05", "5%"], "sources": ["benchmarks/outcome/paired_delta.py"]},
    )


def _approach_task(tried=True):
    key = {"tried": tried}
    if tried:
        key["reasons"] = ["Bootstrap over pairs treats repeats as independent"]
    return OutcomeTask("y", FAMILY_APPROACH, "Was pair-level bootstrap tried?", key)


def test_normalize_text_folds_case_width_and_whitespace():
    assert normalize_text("  Ｆoo\tBAR \n baz ") == "foo bar baz"


@pytest.mark.parametrize(
    "raw",
    [
        "benchmarks/outcome/paired_delta.py",
        "./benchmarks/outcome/paired_delta.py",
        "benchmarks\\outcome\\paired_delta.py",
        "benchmarks/outcome/paired_delta.py:52",
    ],
)
def test_normalize_source_variants(raw):
    assert normalize_source(raw) == "benchmarks/outcome/paired_delta.py"


def test_value_answer_matches_any_accepted_spelling_and_source_line():
    task = _value_task()
    answer = {"value": " 5% ", "source": "./benchmarks/outcome/paired_delta.py:52"}
    assert verify(task, answer, resolve_commit=_no_git)


@pytest.mark.parametrize(
    "answer",
    [
        {"value": "0.1", "source": "benchmarks/outcome/paired_delta.py"},
        {"value": "0.05", "source": "benchmarks/lib/verification_report.py"},
        {"value": "0.05"},
        {"value": 0.05, "source": "benchmarks/outcome/paired_delta.py"},
        "0.05",
    ],
)
def test_value_answer_wrong_missing_or_mistyped_is_incorrect(answer):
    assert not verify(_value_task(), answer, resolve_commit=_no_git)


def test_approach_reason_is_exact_after_normalisation_not_similarity():
    task = _approach_task()
    exact = {
        "tried": True,
        "reason": "bootstrap over pairs  treats REPEATS as independent",
    }
    near = {
        "tried": True,
        "reason": "bootstrap over pairs treats repeats independently",
    }
    assert verify(task, exact, resolve_commit=_no_git)
    assert not verify(task, near, resolve_commit=_no_git)
    assert not verify(task, {"tried": False}, resolve_commit=_no_git)
    assert not verify(
        task, {"tried": "yes", "reason": exact["reason"]}, resolve_commit=_no_git
    )


def test_untried_approach_needs_only_tried_false():
    task = _approach_task(tried=False)
    assert verify(task, {"tried": False}, resolve_commit=_no_git)
    assert not verify(task, {"tried": True, "reason": "x"}, resolve_commit=_no_git)


@pytest.mark.parametrize(
    "family,key",
    [
        (FAMILY_COMMIT, {"commit": "0123456"}),
        (FAMILY_COMMIT, {"commit": _SHA.upper()}),
        (FAMILY_APPROACH, {"tried": "yes"}),
        (FAMILY_APPROACH, {"tried": True}),
        (FAMILY_APPROACH, {"tried": False, "reasons": ["x"]}),
        (FAMILY_VALUE, {"values": [], "sources": ["a.py"]}),
        (FAMILY_VALUE, {"values": ["1"], "sources": [" "]}),
        ("other", {}),
    ],
)
def test_malformed_task_definitions_raise(family, key):
    with pytest.raises(ValueError):
        OutcomeTask("t", family, "q?", key)


def test_load_tasks_rejects_duplicates_and_non_objects(tmp_path):
    item = {
        "id": "a",
        "family": FAMILY_COMMIT,
        "question": "q?",
        "key": {"commit": _SHA},
    }
    good = tmp_path / "good.json"
    good.write_text(json.dumps([item]), encoding="utf-8")
    assert load_tasks(good)[0].key["commit"] == _SHA
    for bad in ([item, item], [], ["a"], [{**item, "key": None}]):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError):
            load_tasks(path)


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    for i in range(2):
        (tmp_path / "f.txt").write_text(str(i), encoding="utf-8")
        _git(tmp_path, "add", "f.txt")
        _git(
            tmp_path,
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-qm",
            f"c{i}",
        )
    return tmp_path


def test_commit_answer_resolved_by_git(repo):
    first = _git(repo, "rev-list", "--max-parents=0", "HEAD")
    task = OutcomeTask("x", FAMILY_COMMIT, "Which commit?", {"commit": first})
    resolve = git_commit_resolver(repo)
    assert verify(task, {"commit": first}, resolve_commit=resolve)
    assert verify(task, {"commit": first[:12].upper()}, resolve_commit=resolve)
    assert not verify(
        task, {"commit": _git(repo, "rev-parse", "HEAD")}, resolve_commit=resolve
    )
    assert not verify(task, {"commit": "HEAD~1"}, resolve_commit=resolve)
    assert not verify(task, {"commit": "--all"}, resolve_commit=resolve)
    assert not verify(task, {"commit": "ffffffff"}, resolve_commit=resolve)


def test_hex_named_ref_does_not_stand_in_for_a_hash_prefix(repo):
    # Codex review 4467463788 on #858: rev-parse would resolve a branch
    # spelled in hex; the resolver consults object names only.
    first = _git(repo, "rev-list", "--max-parents=0", "HEAD")
    ref = next(p for p in ("deadbeef", "cafebabe") if not first.startswith(p))
    _git(repo, "branch", ref, first)
    task = OutcomeTask("x", FAMILY_COMMIT, "Which commit?", {"commit": first})
    assert not verify(task, {"commit": ref}, resolve_commit=git_commit_resolver(repo))


def test_non_commit_objects_sharing_the_prefix_are_ignored(repo):
    first = _git(repo, "rev-list", "--max-parents=0", "HEAD")
    blob = _git(repo, "rev-parse", "HEAD:f.txt")
    resolve = git_commit_resolver(repo)
    assert resolve(first) == first
    assert resolve(blob) is None


def test_resolver_refuses_non_hex(repo):
    with pytest.raises(ValueError):
        git_commit_resolver(repo)("HEAD")
