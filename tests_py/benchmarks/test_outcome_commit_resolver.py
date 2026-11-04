"""Tests for the git commit resolver in benchmarks/outcome/answer_key.py.

Issue #343, slice 2. Every case runs against a real throwaway git
repository: the candidate objects for a prefix come from git's object store,
as in a real run, and the resolver keeps a prefix only when exactly one
candidate is a commit."""

from __future__ import annotations

import os
import subprocess

import pytest

from benchmarks.outcome.answer_key import (
    FAMILY_COMMIT,
    OutcomeTask,
    git_commit_resolver,
    verify,
)


def _no_git(_name):
    raise AssertionError("resolver must not be called")


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
        env={
            **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
            **_ISOLATED_GIT,
        },
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
        # Fixed dates make `first` deterministic; the ref must not be a real
        # prefix of it, or the case would test nothing.
        assert not first.startswith(ref)
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


@pytest.fixture
def crowded_repo(tmp_path):
    """2000 commits and 2000 blobs with fixed content and dates.

    The hashes are deterministic, and 4000 objects over 65536 four-hex
    prefixes all but guarantee both a prefix shared by two commits and one
    shared by a commit and a blob (birthday bound)."""
    _git(tmp_path, "init", "-q")
    blobs = "".join(f"blob\ndata {len(f'b{i}')}\nb{i}\n" for i in range(2000))
    commits = "".join(
        f"commit refs/heads/main\ncommitter t <t@t> 0 +0000\ndata {len(str(i))}\n{i}\n"
        for i in range(2000)
    )
    _git(tmp_path, "fast-import", "--quiet", stdin=blobs + commits)
    listed = _git(tmp_path, "cat-file", "--batch-all-objects", "--batch-check")
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
    first = _git(repo, "rev-list", "--max-parents=0", "HEAD")
    assert git_commit_resolver(repo)(first[:3]) is None


def test_sha256_repository_resolves_full_and_short_names(tmp_path):
    _git(tmp_path, "init", "-q", "--object-format=sha256")
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    _git(tmp_path, "add", "f.txt")
    _git(tmp_path, "commit", "-qm", "c")
    head = _git(tmp_path, "rev-parse", "HEAD")
    assert len(head) == 64
    task = _commit_task(head)
    resolve = git_commit_resolver(tmp_path)
    assert verify(task, {"commit": head}, resolve_commit=resolve)
    assert verify(task, {"commit": head[:10]}, resolve_commit=resolve)


def test_inherited_git_dir_is_ignored(repo, tmp_path_factory, monkeypatch):
    other = tmp_path_factory.mktemp("other")
    _git(other, "init", "-q")
    first = _git(repo, "rev-list", "--max-parents=0", "HEAD")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    assert git_commit_resolver(repo)(first) == first


def test_broken_corpus_raises_instead_of_scoring_incorrect(tmp_path):
    with pytest.raises(subprocess.CalledProcessError, match="returned non-zero"):
        git_commit_resolver(tmp_path / "missing")("abcd")


def test_resolver_refuses_non_hex(repo):
    with pytest.raises(ValueError, match="not a hex object name"):
        git_commit_resolver(repo)("HEAD")


def test_plain_subdirectory_of_a_repo_raises(repo):
    # claude[bot] review 6630792667 on #858: `git -C` would otherwise walk up
    # and resolve answers against the enclosing repository.
    (repo / "plain").mkdir()
    with pytest.raises(ValueError, match="not the root of a git work tree"):
        git_commit_resolver(repo / "plain")


def test_replace_refs_do_not_change_the_answer(crowded_repo):
    # A replace ref that dresses a blob up as a commit would otherwise make
    # the prefix ambiguous among commits.
    repo, by_prefix = crowded_repo
    group = next(
        g for g in by_prefix.values() if sorted(k for k, _ in g) == ["blob", "commit"]
    )
    commit = next(name for kind, name in group if kind == "commit")
    blob = next(name for kind, name in group if kind == "blob")
    other = _git(repo, "rev-parse", "main")
    _git(repo, "replace", "-f", blob, other)
    assert _git(repo, "cat-file", "-t", blob) == "commit"
    assert git_commit_resolver(repo)(commit[:4]) == commit
