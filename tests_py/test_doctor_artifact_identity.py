"""The doctor's artifact identity as data (#730, slice 3: the receipt producer).

``scripts/native_receipt_artifact.py`` builds a receipt's ``artifact`` object from
``identify()``'s fields, not from the check's text, so each path asserts the whole
``Identity``: kind, version, revision, modified, members, location, and the
``unknown``/``fix`` pair that makes the check fail and the producer refuse."""

from mcp_server import doctor_artifact
from mcp_server.doctor_artifact import Identity
from tests_py.test_doctor_artifact import (
    REINSTALL,
    X1,
    _git_replies,
    _imported_from,
    _source_package,
    _wheel_install,
    _without_distribution,
)

MEMBERS = (("mcp_server/a.py", X1),)


def test_an_installed_wheel_is_identified(monkeypatch, tmp_path):
    package, dist = _wheel_install(tmp_path)
    _imported_from(monkeypatch, package, dist)
    assert doctor_artifact.identify() == Identity(
        "wheel", "9.9.9", None, False, MEMBERS, package.resolve()
    )


def test_a_tampered_wheel_is_identified_as_modified(monkeypatch, tmp_path):
    package, dist = _wheel_install(tmp_path, tamper=True)
    _imported_from(monkeypatch, package, dist)
    assert doctor_artifact.identify() == Identity(
        "wheel", "9.9.9", None, True, MEMBERS, package.resolve(),
        altered=("mcp_server/a.py",), fix=REINSTALL,
    )  # fmt: skip


def test_a_wheel_without_record_has_no_identity(monkeypatch, tmp_path):
    package, dist = _wheel_install(tmp_path)
    (dist._path / "RECORD").unlink()
    _imported_from(monkeypatch, package, dist)
    assert doctor_artifact.identify() == Identity(
        "wheel", "9.9.9", None, False, (), package.resolve(),
        unknown="installed hypermnesia-mcp 9.9.9 has no RECORD", fix=REINSTALL,
    )  # fmt: skip


def test_a_tree_outside_git_is_identified(monkeypatch, tmp_path):
    package = _source_package(tmp_path, git=False)
    _without_distribution(monkeypatch, package)
    assert doctor_artifact.identify() == Identity(
        "source-tree", None, None, False, MEMBERS, package.resolve()
    )


def test_a_clean_checkout_is_identified(monkeypatch, tmp_path):
    package = _source_package(tmp_path)
    _without_distribution(monkeypatch, package)
    _git_replies(monkeypatch, "abc123", "")
    assert doctor_artifact.identify() == Identity(
        "source-tree", None, "abc123", False, MEMBERS, package.resolve(),
        in_git=True,
    )  # fmt: skip


def test_a_changed_checkout_is_identified_as_modified(monkeypatch, tmp_path):
    package = _source_package(tmp_path)
    _without_distribution(monkeypatch, package)
    _git_replies(monkeypatch, "abc123", " M mcp_server/a.py")
    found = doctor_artifact.identify()
    assert (found.kind, found.revision, found.modified) == (
        "source-tree",
        "abc123",
        True,
    )
    assert (found.unknown, found.fix) == (None, None)


def test_a_failed_git_leaves_the_identity_unknown(monkeypatch, tmp_path):
    package = _source_package(tmp_path)
    _without_distribution(monkeypatch, package)
    _git_replies(monkeypatch, "abc123", None)
    found = doctor_artifact.identify()
    assert (found.kind, found.in_git, found.modified) == ("source-tree", True, False)
    assert found.unknown == "revision state unknown: `git status` failed"
    assert found.fix == (
        f"Run `git -C {package.parent} status` to see why git cannot answer"
    )
