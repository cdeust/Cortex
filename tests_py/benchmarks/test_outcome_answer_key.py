"""Tests for benchmarks/outcome/answer_key.py (issue #343, slice 2).

The commit family is exercised against a real throwaway git repository, so
abbreviation and ambiguity are decided by git, as in a real run."""

from __future__ import annotations

import json
import os
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


_ISOLATED_GIT = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
    "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
}


def _git(repo, *args, stdin=None):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        input=stdin,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **_ISOLATED_GIT},
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    for i in range(2):
        (tmp_path / "f.txt").write_text(str(i), encoding="utf-8")
        _git(tmp_path, "add", "f.txt")
        _git(tmp_path, "commit", "-qm", f"c{i}")
    return tmp_path


def _commit_task(sha):
    return OutcomeTask("x", FAMILY_COMMIT, "Which commit?", {"commit": sha})


def test_commit_answer_resolved_by_git(repo):
    first = _git(repo, "rev-list", "--max-parents=0", "HEAD")
    task = _commit_task(first)
    resolve = git_commit_resolver(repo)
    assert verify(task, {"commit": first}, resolve_commit=resolve)
    assert verify(task, {"commit": first[:12].upper()}, resolve_commit=resolve)
    head = _git(repo, "rev-parse", "HEAD")
    for wrong in (head, "HEAD~1", "--all", "ffffffff", "", " ", 7, None, "0x" + first):
        assert not verify(task, {"commit": wrong}, resolve_commit=resolve), wrong
    assert not verify(task, {"commit": "a" * 200_000}, resolve_commit=_no_git)


def test_hex_named_ref_does_not_stand_in_for_a_hash_prefix(repo):
    # Codex review 4467463788 and the claude[bot] review on #858: rev-parse
    # resolves a ref spelled in hex; the resolver consults object names only.
    first = _git(repo, "rev-list", "--max-parents=0", "HEAD")
    for ref in ("deadbeef", "2024"):
        if not first.startswith(ref):
            _git(repo, "tag", ref, first)
            assert not verify(
                _commit_task(first),
                {"commit": ref},
                resolve_commit=git_commit_resolver(repo),
            )


def test_non_commit_objects_sharing_the_prefix_are_ignored(repo):
    first = _git(repo, "rev-list", "--max-parents=0", "HEAD")
    _git(repo, "tag", "-a", "-m", "annotated", "v1", first)
    resolve = git_commit_resolver(repo)
    assert resolve(first) == first
    assert resolve(_git(repo, "rev-parse", "HEAD:f.txt")) is None
    assert resolve(_git(repo, "rev-parse", "v1")) is None


def test_ambiguous_commit_prefix_is_incorrect(tmp_path):
    # Fixed content and dates make the hashes deterministic; 2000 commits
    # over 65536 four-hex prefixes all but guarantee a shared prefix.
    _git(tmp_path, "init", "-q")
    stream = "".join(
        f"commit refs/heads/main\ncommitter t <t@t> 0 +0000\ndata {len(str(i))}\n{i}\n"
        for i in range(2000)
    )
    _git(tmp_path, "fast-import", "--quiet", stdin=stream)
    by_prefix = {}
    for sha in _git(tmp_path, "rev-list", "main").split():
        by_prefix.setdefault(sha[:4], []).append(sha)
    first, _ = next(group for group in by_prefix.values() if len(group) > 1)
    resolve = git_commit_resolver(tmp_path)
    assert not verify(
        _commit_task(first), {"commit": first[:4]}, resolve_commit=resolve
    )
    assert verify(_commit_task(first), {"commit": first}, resolve_commit=resolve)


def test_inherited_git_dir_is_ignored(repo, tmp_path_factory, monkeypatch):
    other = tmp_path_factory.mktemp("other")
    _git(other, "init", "-q")
    first = _git(repo, "rev-list", "--max-parents=0", "HEAD")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    assert git_commit_resolver(repo)(first) == first


def test_broken_corpus_raises_instead_of_scoring_incorrect(tmp_path):
    with pytest.raises(subprocess.CalledProcessError):
        git_commit_resolver(tmp_path / "missing")("abcd")


def test_resolver_refuses_non_hex(repo):
    with pytest.raises(ValueError, match="not a hex object name"):
        git_commit_resolver(repo)("HEAD")
