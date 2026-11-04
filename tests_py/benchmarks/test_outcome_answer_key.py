"""Tests for benchmarks/outcome/answer_key.py (issue #343, slice 2).

The git-backed commit resolver is tested in test_outcome_commit_resolver.py."""

from __future__ import annotations

import json

import pytest

from benchmarks.outcome.answer_key import (
    FAMILY_APPROACH,
    FAMILY_COMMIT,
    FAMILY_VALUE,
    OutcomeTask,
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
    "family,key,match",
    [
        (FAMILY_COMMIT, {"commit": "0123456"}, "full lowercase hex"),
        (FAMILY_COMMIT, {"commit": _SHA.upper()}, "full lowercase hex"),
        (FAMILY_COMMIT, {"commit": _SHA, "note": "x"}, "unknown key fields"),
        (FAMILY_APPROACH, {"tried": "yes"}, "must be a bool"),
        (FAMILY_APPROACH, {"tried": True}, "non-empty list"),
        (FAMILY_APPROACH, {"tried": True, "reasons": "x"}, "non-empty list"),
        (FAMILY_APPROACH, {"tried": True, "reasons": [1]}, "non-empty strings"),
        (FAMILY_APPROACH, {"tried": False, "reasons": ["x"]}, "has no reasons"),
        (FAMILY_APPROACH, {"tried": False, "reason": ["x"]}, "unknown key fields"),
        (FAMILY_VALUE, {"values": [], "sources": ["a.py"]}, "non-empty list"),
        (FAMILY_VALUE, {"values": ["1"], "sources": [" "]}, "non-empty strings"),
        (FAMILY_VALUE, {"values": ["1"], "sources": ["./"]}, "inside the repo"),
        (FAMILY_VALUE, {"values": ["1"], "sources": ["/etc/a.py"]}, "inside the repo"),
        (FAMILY_VALUE, {"values": ["1"], "sources": ["../a.py"]}, "inside the repo"),
        ("other", {}, "unknown family"),
        (FAMILY_COMMIT, None, "key must be a mapping"),
    ],
)
def test_malformed_task_definitions_raise(family, key, match):
    with pytest.raises(ValueError, match=match):
        OutcomeTask("t", family, "q?", key)


def test_blank_task_id_raises():
    with pytest.raises(ValueError, match="task_id"):
        OutcomeTask("  ", FAMILY_COMMIT, "q?", {"commit": _SHA})


@pytest.mark.parametrize(
    "source",
    [
        "benchmarks/outcome/paired_delta.py#L52",
        "benchmarks/outcome/paired_delta.py:52-60",
        "benchmarks/outcome/paired_delta.py:52:3",
        "benchmarks/outcome/paired_delta.py:\u0665",
    ],
)
def test_source_spellings_outside_the_documented_rule_do_not_match(source):
    answer = {"value": "0.05", "source": source}
    assert not verify(_value_task(), answer, resolve_commit=_no_git)


def test_task_is_hashable_by_id():
    task = _value_task()
    assert hash(task) == hash(task.task_id)
    assert {task} == {_value_task()}


def test_load_tasks_error_names_the_file(tmp_path):
    path = tmp_path / "tasks.json"
    item = {"family": FAMILY_VALUE, "question": "q?", "key": {}}
    path.write_text(json.dumps([item]), encoding="utf-8")
    with pytest.raises(ValueError, match="tasks.json: task_id"):
        load_tasks(path)


def test_sha256_key_is_accepted_and_key_is_frozen():
    key = {"values": ["1"], "sources": ["a.py"]}
    task = OutcomeTask("t", FAMILY_VALUE, "q?", key)
    key["values"].append("2")
    assert task.key["values"] == ("1",)
    with pytest.raises(TypeError):
        task.key["values"] = ("2",)
    assert OutcomeTask("s", FAMILY_COMMIT, "q?", {"commit": "a" * 64})


def _item(**overrides):
    item = {
        "id": "a",
        "family": FAMILY_COMMIT,
        "question": "q?",
        "key": {"commit": _SHA},
    }
    return {**item, **overrides}


def test_load_tasks_reads_a_valid_list(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps([_item()]), encoding="utf-8")
    assert load_tasks(path)[0].key["commit"] == _SHA


@pytest.mark.parametrize(
    "content,match",
    [
        ([_item(), _item()], "duplicate task ids"),
        ([], "non-empty JSON list"),
        ({"a": 1}, "non-empty JSON list"),
        (["a"], "'key' object"),
        ([_item(key=None)], "'key' object"),
        (
            [{"family": FAMILY_COMMIT, "question": "q?", "key": {"commit": _SHA}}],
            "task_id",
        ),
        ([_item(question=None)], "question"),
    ],
)
def test_load_tasks_rejects_malformed_files(tmp_path, content, match):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        load_tasks(path)
