"""Corpus validation in benchmarks/outcome/commit_resolver.py (issue #343).

``git_commit_resolver`` must refuse, before any answer is scored, a corpus
whose objects would be read from somewhere other than the snapshot it was
given: an enclosing repository, a linked worktree's common directory, or a
store borrowed through ``objects/info/alternates``, a ``commondir`` file, a
``cp -r`` copy of ``.git`` or a symlink at ``.git`` or under ``objects/``.
A bare repository is the natural read-only snapshot and is accepted. Global
git config never reaches the resolver, and git older than 2.32 is refused."""

from __future__ import annotations

import os
import shutil
import subprocess

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


def test_commondir_pointing_elsewhere_raises(repo, tmp_path):
    # claude[bot] review 6631043421 on #858: the worktree test fails on the
    # git-dir comparison, so this case pins the common-dir comparison alone.
    other = make_repo(tmp_path / "other")
    (repo / ".git" / "commondir").write_text(str(other / ".git"), encoding="utf-8")
    with pytest.raises(ValueError, match=r"\(common dir"):
        git_commit_resolver(repo)


def test_bare_clone_with_alternates_raises(repo, tmp_path):
    bare = tmp_path / "shared.git"
    git(tmp_path, "clone", "-q", "--bare", "--shared", str(repo), str(bare))
    with pytest.raises(ValueError, match="alternates"):
        git_commit_resolver(bare)


def test_copied_git_directory_is_rejected(repo, tmp_path):
    copy = tmp_path / "copy.git"
    shutil.copytree(repo / ".git", copy)
    with pytest.raises(ValueError, match="not a self-contained repository root"):
        git_commit_resolver(copy)


def test_symlinked_git_directory_raises(repo, tmp_path):
    link = tmp_path / "linked"
    link.mkdir()
    (link / ".git").symlink_to(repo / ".git")
    with pytest.raises(ValueError, match="symlink"):
        git_commit_resolver(link)


def test_global_config_does_not_reach_the_resolver(repo, tmp_path, monkeypatch):
    # `safe.bareRepository=explicit` (git >= 2.38) in a global config would
    # refuse the bare corpus if the resolver read it.
    bare = tmp_path / "bare.git"
    git(tmp_path, "clone", "-q", "--bare", "--no-local", str(repo), str(bare))
    home = tmp_path / "home"
    home.mkdir()
    config = "[safe]\n\tbareRepository = explicit\n"
    (home / ".gitconfig").write_text(config, encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    # Positive control: git < 2.38 ignores the setting, so the test would
    # prove nothing there.
    plain = subprocess.run(
        ["git", "-C", str(bare), "rev-parse", "--git-dir"],
        capture_output=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    )
    if plain.returncode == 0:
        pytest.skip("this git ignores safe.bareRepository; isolation untestable")
    head = git(repo, "rev-parse", "HEAD")
    assert git_commit_resolver(bare)(head[:8]) == head


def _fake_git_version(monkeypatch, output, returncode=0):
    real_run = subprocess.run

    def fake_run(args, **kwargs):
        if args == ["git", "version"]:
            if returncode:
                raise subprocess.CalledProcessError(returncode, args, "", "boom")
            return subprocess.CompletedProcess(args, 0, output, "")
        return real_run(args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)


@pytest.mark.parametrize("output", ["git version 2.31.9\n", "git version garbage\n"])
def test_old_or_unparsable_git_is_refused(monkeypatch, repo, output):
    _fake_git_version(monkeypatch, output)
    with pytest.raises(RuntimeError, match="git >= 2.32 required"):
        git_commit_resolver(repo)


def test_git_2_32_is_accepted(monkeypatch, repo):
    _fake_git_version(monkeypatch, "git version 2.32.0\n")
    head = git(repo, "rev-parse", "HEAD")
    assert git_commit_resolver(repo)(head[:8]) == head


def test_failing_git_version_raises_runtime_error(monkeypatch, repo):
    _fake_git_version(monkeypatch, "", returncode=1)
    with pytest.raises(RuntimeError, match="git version failed: boom"):
        git_commit_resolver(repo)


@pytest.mark.parametrize("relative", ["objects", "objects/pack", "objects/ab"])
def test_symlink_under_objects_raises(repo, tmp_path, relative):
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", "--no-local", str(repo), str(clone))
    target = clone / ".git" / relative
    elsewhere = tmp_path / "elsewhere"
    if target.exists():
        shutil.move(str(target), str(elsewhere))
    else:
        elsewhere.mkdir()
    target.symlink_to(elsewhere)
    with pytest.raises(ValueError, match="symlink"):
        git_commit_resolver(clone)
