"""Corpus validation in benchmarks/outcome/commit_resolver.py (issue #343).

``git_commit_resolver`` must refuse, before any answer is scored, a corpus
whose objects would be read from somewhere other than the snapshot it was
given: an enclosing repository, a linked worktree's common directory, or a
store borrowed through ``objects/info/alternates``. A bare repository is the
natural read-only snapshot and is accepted."""

from __future__ import annotations

import pytest

from benchmarks.outcome.commit_resolver import git_commit_resolver
from tests_py.benchmarks.outcome_git import git, make_repo


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "corpus")


def test_missing_path_raises_with_git_message(tmp_path):
    with pytest.raises(RuntimeError, match="failed in"):
        git_commit_resolver(tmp_path / "missing")


def test_directory_outside_any_repo_raises(tmp_path):
    (tmp_path / "plain").mkdir()
    with pytest.raises(RuntimeError, match="not a git repository"):
        git_commit_resolver(tmp_path / "plain")


def test_plain_subdirectory_of_a_repo_raises(repo):
    # claude[bot] review 6630792667 on #858: `git -C` would otherwise walk up
    # and resolve answers against the enclosing repository.
    (repo / "plain").mkdir()
    with pytest.raises(ValueError, match="not a self-contained repository root"):
        git_commit_resolver(repo / "plain")


def test_git_directory_itself_raises(repo):
    with pytest.raises(ValueError, match="not a self-contained repository root"):
        git_commit_resolver(repo / ".git")


def test_bare_clone_is_accepted(repo, tmp_path):
    bare = tmp_path / "bare.git"
    git(tmp_path, "clone", "-q", "--bare", "--no-local", str(repo), str(bare))
    head = git(repo, "rev-parse", "HEAD")
    assert git_commit_resolver(bare)(head[:8]) == head


def test_linked_worktree_raises(repo, tmp_path):
    git(repo, "worktree", "add", "-q", str(tmp_path / "wt"))
    with pytest.raises(ValueError, match="not a self-contained repository root"):
        git_commit_resolver(tmp_path / "wt")


def test_borrowed_object_store_raises(repo, tmp_path):
    shared = tmp_path / "shared"
    git(tmp_path, "clone", "-q", "--shared", str(repo), str(shared))
    with pytest.raises(ValueError, match="alternates"):
        git_commit_resolver(shared)
