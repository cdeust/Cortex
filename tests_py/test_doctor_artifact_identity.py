"""The doctor's artifact identity as data (#730, slice 3: the receipt producer).

``scripts/native_receipt_artifact.py`` builds a receipt's ``artifact`` object from
``identify()``'s fields, not from the check's text, so each path asserts the whole
``Identity``: kind, version, revision, modified, members, location, and the
``unknown``/``fix`` pair that makes the check fail and the producer refuse."""

import py_compile
import sys

from mcp_server import doctor_artifact
from mcp_server.doctor_artifact import Identity
from tests_py.test_doctor_bytecode import _forge
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


def test_a_package_file_absent_from_record_is_an_alteration(monkeypatch, tmp_path):
    # Codex security review on #957: an unlisted module, extension or sourceless
    # .pyc runs while every RECORD row still matches.
    package, dist = _wheel_install(tmp_path)
    (package / "evil.py").write_bytes(b"x = 3\n")
    (package / "sub").mkdir()
    (package / "sub" / "loose.pyc").write_bytes(b"\0")
    _imported_from(monkeypatch, package, dist)
    found = doctor_artifact.identify()
    assert found.altered == ("mcp_server/evil.py", "mcp_server/sub/loose.pyc")
    assert (found.modified, found.fix) == (True, REINSTALL)


def test_import_bytecode_is_not_an_alteration(monkeypatch, tmp_path):
    package, dist = _wheel_install(tmp_path)
    py_compile.compile(str(package / "a.py"), doraise=True)
    _imported_from(monkeypatch, package, dist)
    found = doctor_artifact.identify()
    assert (found.altered, found.modified, found.fix) == ((), False, None)


def test_forged_import_bytecode_is_an_alteration(monkeypatch, tmp_path):
    # Codex security review on #957: a timestamp-valid cache runs in place of
    # the RECORD-matching source.
    package, dist = _wheel_install(tmp_path)
    _forge(package / "a.py")
    _imported_from(monkeypatch, package, dist)
    found = doctor_artifact.identify()
    tag = sys.implementation.cache_tag
    assert found.altered == (f"mcp_server/__pycache__/a.{tag}.pyc",)
    assert (found.modified, found.fix) == (True, REINSTALL)


def test_a_file_listed_without_a_hash_is_an_alteration(monkeypatch, tmp_path):
    # Codex review on #957: `mcp_server/b.py,,` is never hashed nor digested, so
    # its content could change while the receipt stayed `modified: false`.
    package, dist = _wheel_install(tmp_path)
    (package / "b.py").write_bytes(b"y = 1\n")
    _imported_from(monkeypatch, package, dist)
    found = doctor_artifact.identify()
    assert (found.altered, found.modified) == (("mcp_server/b.py",), True)


def test_unrecorded_names_files_relative_to_the_package(tmp_path):
    package = tmp_path / "mcp_server"
    (package / "__pycache__").mkdir(parents=True)
    (package / "__pycache__" / "a.pyc").write_bytes(b"\0")
    (package / "a.py").write_bytes(b"")
    (package / "b.so").write_bytes(b"")
    listed = {"mcp_server/a.py"}
    assert doctor_artifact.unrecorded(package, listed) == ["mcp_server/b.so"]
