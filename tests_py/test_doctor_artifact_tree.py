"""Runtime artifact identity of a source tree (#729, slice 2: review notes on #887).

A checkout is digested over the files git keeps in its tree, a tree without
``.git`` is named by its digest alone, and a wheel whose RECORD hashes no
package member is described as the tree it is."""

import subprocess

from mcp_server import doctor, doctor_artifact
from tests_py.test_doctor_artifact import (
    SUFFIX,
    X1,
    SOURCE,
    _git_replies,
    _imported_from,
    _source_package,
    _wheel_install,
    _without_distribution,
)


def test_tree_outside_git_is_named_by_its_digest(monkeypatch, tmp_path):
    # Review note on #887: without .git, the fix advised `git status`, which
    # cannot help; such a tree has no revision, only its digest.
    package = _source_package(tmp_path, git=False)
    _without_distribution(monkeypatch, package)
    calls = _git_replies(monkeypatch, None, None)
    check = doctor_artifact.artifact_identity(doctor.Check)
    digest = doctor_artifact.members_digest([("mcp_server/a.py", X1)])
    assert (check.name, check.ok, check.optional) == (doctor_artifact.NAME, True, True)
    assert check.fix == ""
    assert check.detail == (
        f"source tree {package.parent} outside git (version unknown), "
        f"1 mcp_server files, digest {digest}{SUFFIX}"
    )
    assert calls == []


def test_checkout_without_a_commit_has_no_revision(monkeypatch, tmp_path):
    package = _source_package(tmp_path)
    _without_distribution(monkeypatch, package)
    _git_replies(monkeypatch, None, "")
    check = doctor_artifact.artifact_identity(doctor.Check)
    assert check.ok
    assert check.detail.startswith(f"source tree {package.parent} at no git revision (")


def test_wheel_record_without_package_hashes_is_a_source_tree(monkeypatch, tmp_path):
    package, dist = _wheel_install(tmp_path)
    (dist._path / "RECORD").write_text("mcp_server/a.py,,\n")
    _imported_from(monkeypatch, package, dist)
    check = doctor_artifact.artifact_identity(doctor.Check)
    digest = doctor_artifact.members_digest([("mcp_server/a.py", X1)])
    assert (check.name, check.ok, check.optional) == (doctor_artifact.NAME, True, True)
    assert check.detail == (
        f"source tree {package.parent} outside git (version 9.9.9), "
        f"1 mcp_server files, digest {digest}{SUFFIX}"
    )


def test_failed_git_listing_is_not_a_known_tree(monkeypatch, tmp_path):
    package = _source_package(tmp_path)
    _without_distribution(monkeypatch, package)
    _git_replies(monkeypatch, "abc123", "", listed=None)
    check = doctor_artifact.artifact_identity(doctor.Check)
    assert (check.ok, check.optional) == (False, True)
    assert check.detail.endswith("; revision state unknown: `git ls-files` failed")
    assert check.fix == (
        f"Run `git -C {package.parent} ls-files` to see why git cannot answer"
    )


def test_listed_member_deleted_from_disk_is_skipped(tmp_path):
    package = _source_package(tmp_path)
    listed = ["mcp_server/a.py", "mcp_server/gone.py"]
    assert doctor_artifact.tree_members(package, listed) == [("mcp_server/a.py", X1)]


def _git(cwd, *argv):
    subprocess.run(["git", *argv], cwd=cwd, check=True, capture_output=True)


def test_git_ignored_file_leaves_the_digest_unchanged(monkeypatch, tmp_path):
    # Review note on #887: an ignored .DS_Store changed the tree digest while
    # the wheel (hatchling honours .gitignore) left it out. Real git, no fake.
    package = _source_package(tmp_path)
    (package.parent / ".git").rmdir()
    _git(package.parent, "init", "-q")
    (package.parent / ".gitignore").write_text(".DS_Store\n")
    (package / "untracked.py").write_bytes(SOURCE)
    _git(package.parent, "add", ".gitignore", "mcp_server/a.py")
    (package / ".DS_Store").write_bytes(b"\0")
    _without_distribution(monkeypatch, package)
    check = doctor_artifact.artifact_identity(doctor.Check)
    members = [("mcp_server/a.py", X1), ("mcp_server/untracked.py", X1)]
    assert check.ok, check.detail
    assert f"2 mcp_server files, digest {doctor_artifact.members_digest(members)}" in (
        check.detail
    )
