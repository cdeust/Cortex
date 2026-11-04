"""Tests for benchmarks/outcome/commit_resolver.py.

Issue #343, slice 2. Prefix resolution and ``check_commit_keys`` run against
real throwaway repositories (``outcome_git``): the candidate objects for a
prefix come from git's object store, and the resolver keeps a prefix only
when exactly one candidate is a commit. Answers rejected before git is called
use ``_no_git``. Corpus validation is in test_outcome_corpus_check.py."""

from __future__ import annotations

import pytest

from benchmarks.outcome.answer_key import FAMILY_COMMIT, OutcomeTask, verify
from benchmarks.outcome.commit_resolver import check_commit_keys, git_commit_resolver
from tests_py.benchmarks.outcome_git import git, make_repo


def _no_git(_name):
    raise AssertionError("resolver must not be called")


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path)


def _commit_task(sha):
    return OutcomeTask("x", FAMILY_COMMIT, "Which commit?", {"commit": sha})


def test_commit_answer_resolved_by_git(repo):
    first = git(repo, "rev-list", "--max-parents=0", "HEAD")
    task = _commit_task(first)
    resolve = git_commit_resolver(repo)
    assert verify(task, {"commit": first}, resolve_commit=resolve)
    assert verify(task, {"commit": first[:12].upper()}, resolve_commit=resolve)
    head = git(repo, "rev-parse", "HEAD")
    for wrong in (head, "HEAD~1", "--all", "ffffffff", "", " ", 7, None, "0x" + first):
        assert not verify(task, {"commit": wrong}, resolve_commit=resolve), wrong
    assert not verify(task, {"commit": "a" * 200_000}, resolve_commit=_no_git)


def test_hex_named_ref_does_not_stand_in_for_a_hash_prefix(repo):
    # Codex review 4467463788 and the claude[bot] reviews on #858: a general
    # revision lookup would resolve a ref spelled in hex; the resolver lists
    # object names only (`--disambiguate`), so neither a tag nor a branch counts.
    first = git(repo, "rev-list", "--max-parents=0", "HEAD")
    for ref in ("deadbeef", "2024"):
        # Fixed dates make `first` deterministic; the ref must not be a real
        # prefix of it, or the case would test nothing.
        assert not first.startswith(ref)
        git(repo, "tag", ref, first)
        git(repo, "branch", f"{ref}0", first)
        git(repo, "tag", "-a", "-m", "m", f"{ref}1", first)
        resolve = git_commit_resolver(repo)
        assert not verify(_commit_task(first), {"commit": ref}, resolve_commit=resolve)
        for name in (f"{ref}0", f"{ref}1"):
            assert not first.startswith(name)
            assert resolve(name) is None


def test_full_hash_of_a_non_commit_object_names_no_commit(repo):
    first = git(repo, "rev-list", "--max-parents=0", "HEAD")
    git(repo, "tag", "-a", "-m", "annotated", "v1", first)
    resolve = git_commit_resolver(repo)
    assert resolve(first) == first
    assert resolve(git(repo, "rev-parse", "HEAD:f.txt")) is None
    assert resolve(git(repo, "rev-parse", "v1")) is None


@pytest.fixture
def crowded_repo(tmp_path):
    """2000 commits and 2000 blobs with fixed content and dates.

    The hashes are deterministic, and 4000 objects over 65536 four-hex
    prefixes all but guarantee both a prefix shared by two commits and one
    shared by a commit and a blob (birthday bound)."""
    git(tmp_path, "init", "-q")
    blobs = "".join(f"blob\ndata {len(f'b{i}')}\nb{i}\n" for i in range(2000))
    commits = "".join(
        f"commit refs/heads/main\ncommitter t <t@t> 0 +0000\ndata {len(str(i))}\n{i}\n"
        for i in range(2000)
    )
    git(tmp_path, "fast-import", "--quiet", stdin=blobs + commits)
    listed = git(tmp_path, "cat-file", "--batch-all-objects", "--batch-check")
    by_prefix = {}
    for name, kind, _size in (line.split() for line in listed.splitlines()):
        by_prefix.setdefault(name[:4], []).append((kind, name))
    return tmp_path, by_prefix


def test_prefix_shared_by_two_commits_is_incorrect(crowded_repo):
    repo, by_prefix = crowded_repo
    group = next(g for g in by_prefix.values() if [k for k, _ in g].count("commit") > 1)
    first = next(name for kind, name in group if kind == "commit")
    resolve = git_commit_resolver(repo)
    assert resolve(first[:4]) is None
    assert not verify(
        _commit_task(first), {"commit": first[:4]}, resolve_commit=resolve
    )
    assert verify(_commit_task(first), {"commit": first}, resolve_commit=resolve)


def test_prefix_shared_by_one_commit_and_a_blob_names_the_commit(crowded_repo):
    # Documented rule: unique among commits; a blob does not make it ambiguous.
    repo, by_prefix = crowded_repo
    group = next(
        g for g in by_prefix.values() if sorted(k for k, _ in g) == ["blob", "commit"]
    )
    commit = next(name for kind, name in group if kind == "commit")
    assert git_commit_resolver(repo)(commit[:4]) == commit


def test_prefix_below_git_minimum_names_nothing(repo):
    first = git(repo, "rev-list", "--max-parents=0", "HEAD")
    assert git_commit_resolver(repo)(first[:3]) is None


def test_sha256_repository_resolves_full_and_short_names(tmp_path):
    git(tmp_path, "init", "-q", "--object-format=sha256")
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    git(tmp_path, "add", "f.txt")
    git(tmp_path, "commit", "-qm", "c")
    head = git(tmp_path, "rev-parse", "HEAD")
    assert len(head) == 64
    task = _commit_task(head)
    resolve = git_commit_resolver(tmp_path)
    assert verify(task, {"commit": head}, resolve_commit=resolve)
    assert verify(task, {"commit": head[:10]}, resolve_commit=resolve)


def test_inherited_git_dir_is_ignored(repo, tmp_path_factory, monkeypatch):
    other = tmp_path_factory.mktemp("other")
    git(other, "init", "-q")
    first = git(repo, "rev-list", "--max-parents=0", "HEAD")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    assert git_commit_resolver(repo)(first) == first


def test_resolver_refuses_non_hex(repo):
    with pytest.raises(ValueError, match="not a lowercase hex object name"):
        git_commit_resolver(repo)("HEAD")


def test_replace_refs_do_not_change_the_answer(crowded_repo):
    # A replace ref that dresses a blob up as a commit would otherwise make
    # the prefix ambiguous among commits.
    repo, by_prefix = crowded_repo
    group = next(
        g for g in by_prefix.values() if sorted(k for k, _ in g) == ["blob", "commit"]
    )
    commit = next(name for kind, name in group if kind == "commit")
    blob = next(name for kind, name in group if kind == "blob")
    other = git(repo, "rev-parse", "main")
    git(repo, "replace", "-f", blob, other)
    assert git(repo, "cat-file", "-t", blob) == "commit"
    assert git_commit_resolver(repo)(commit[:4]) == commit


def test_answer_longer_than_the_key_names_nothing(repo):
    # Probe of git 2.43: `--disambiguate=<sha1>0` lists nothing in a SHA-1
    # repository, so an over-length answer is incorrect rather than padded.
    first = git(repo, "rev-list", "--max-parents=0", "HEAD")
    resolve = git_commit_resolver(repo)
    assert resolve(first + "0") is None
    assert not verify(_commit_task(first), {"commit": "a" * 65}, resolve_commit=_no_git)


def test_check_commit_keys_rejects_a_key_outside_the_corpus(repo):
    first = git(repo, "rev-list", "--max-parents=0", "HEAD")
    blob = git(repo, "rev-parse", "HEAD:f.txt")
    resolve = git_commit_resolver(repo)
    check_commit_keys([_commit_task(first)], resolve)
    for key in (blob, "0" * 40, "a" * 64):
        with pytest.raises(ValueError, match="is not a commit of the corpus"):
            check_commit_keys([_commit_task(key)], resolve)


def test_check_commit_keys_skips_other_families_and_names_the_task(repo):
    first = git(repo, "rev-list", "--max-parents=0", "HEAD")
    resolve = git_commit_resolver(repo)
    other = OutcomeTask("v", "decided_value", "q?", {"values": ["1"], "sources": ["a"]})
    check_commit_keys([other, _commit_task(first)], resolve)
    bad = OutcomeTask("bad", FAMILY_COMMIT, "q?", {"commit": "0" * 40})
    with pytest.raises(ValueError, match=r"task 'bad'"):
        check_commit_keys([_commit_task(first), bad], resolve)


def test_tree_hash_whitespace_and_case(repo):
    first = git(repo, "rev-list", "--max-parents=0", "HEAD")
    resolve = git_commit_resolver(repo)
    assert resolve(git(repo, "rev-parse", "HEAD^{tree}")) is None
    padded = {"commit": f"  {first[:10]}\n"}
    assert verify(_commit_task(first), padded, resolve_commit=resolve)
    with pytest.raises(ValueError, match="lowercase hex"):
        resolve(first.upper())
