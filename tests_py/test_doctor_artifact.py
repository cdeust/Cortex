"""Runtime artifact identity check contracts. Source: issue #729 (slice 1)."""

from importlib import metadata

from mcp_server import doctor, doctor_artifact

# source: python3 -c "import base64, hashlib; print(base64.urlsafe_b64encode(
# hashlib.sha256(b'x = 1\n').digest()))", run 2026-11-05, padding removed.
X1 = "sha256=nia_NpkRxFwkPGhBR7I_yeHc_PJX0pmhxjIBam_NM_Q"
SOURCE = b"x = 1\n"
SUFFIX = "; source evidence, not a distributed artifact"


def _wheel_install(tmp_path, *, tamper: bool = False):
    """A site-packages holding mcp_server/a.py and its RECORD, PEP 376 layout.

    The rows before the package member are the ones the check must skip: an
    installer script outside the package (hashed) and the RECORD itself."""
    site = tmp_path / "site"
    package = site / "mcp_server"
    package.mkdir(parents=True)
    (package / "a.py").write_bytes(SOURCE)
    info = site / "hypermnesia_mcp-9.9.9.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Name: hypermnesia-mcp\nVersion: 9.9.9\n")
    rows = [
        f"../../../bin/hypermnesia-mcp,{X1},6",
        "hypermnesia_mcp-9.9.9.dist-info/RECORD,,",
        "mcp_server/b.py,,",
        f"mcp_server/a.py,{X1},6",
    ]
    (info / "RECORD").write_text("\n".join(rows) + "\n")
    if tamper:
        (package / "a.py").write_bytes(b"x = 2\n")
    return package, metadata.PathDistribution(info)


def _imported_from(monkeypatch, package, dist):
    monkeypatch.setattr(doctor_artifact.mcp_server, "__file__", str(package / "x"))
    monkeypatch.setattr(doctor_artifact.metadata, "distribution", lambda name: dist)


def _git_replies(monkeypatch, revision, changes):
    calls = []

    def fake(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return {"rev-parse": revision, "status": changes}[cmd[1]]

    monkeypatch.setattr(doctor_artifact, "run_with_hard_timeout", fake)
    return calls


def _raise_absent(name):
    raise metadata.PackageNotFoundError(name)


def _without_distribution(monkeypatch, package):
    monkeypatch.setattr(doctor_artifact.mcp_server, "__file__", str(package / "x"))
    monkeypatch.setattr(doctor_artifact.metadata, "distribution", _raise_absent)


def _source_package(tmp_path):
    package = tmp_path / "checkout" / "mcp_server"
    (package / "__pycache__").mkdir(parents=True)
    (package / "__pycache__" / "a.cpython-311.pyc").write_bytes(b"\0")
    (package / "__pycache__" / "notes.txt").write_bytes(b"\0")
    (package / "stray.pyc").write_bytes(b"\0")
    (package / "a.py").write_bytes(SOURCE)
    return package


def test_record_hash_is_the_unpadded_record_encoding():
    assert doctor_artifact.record_hash(SOURCE) == X1


def test_digest_is_one_sha256_over_sorted_lines():
    a = [("mcp_server/b.py", "sha256=B"), ("mcp_server/a.py", "sha256=A")]
    # source: the sha256 hex of the two sorted lines joined by a newline, 2026-11-05.
    expected = "7e5a443a3512b1a7b1ea8905892534d6f1ef121dab7431a48fbd5d3a106fd517"
    assert doctor_artifact.members_digest(a) == expected


def test_tree_members_skip_bytecode_only(tmp_path):
    package = _source_package(tmp_path)
    assert doctor_artifact.tree_members(package) == [("mcp_server/a.py", X1)]


def test_wheel_members_keep_hashed_package_rows(tmp_path):
    _, dist = _wheel_install(tmp_path)
    assert doctor_artifact.wheel_members(dist) == [("mcp_server/a.py", X1)]


def test_wheel_without_record_has_no_members(tmp_path):
    _, dist = _wheel_install(tmp_path)
    (dist._path / "RECORD").unlink()
    assert doctor_artifact.wheel_members(dist) == []


def test_deleted_installed_member_fails(monkeypatch, tmp_path):
    # Python >= 3.12 drops absent files from Distribution.files; the check
    # reads RECORD itself so a deleted member is still reported.
    package, dist = _wheel_install(tmp_path)
    (package / "a.py").unlink()
    _imported_from(monkeypatch, package, dist)
    check = doctor_artifact.artifact_identity(doctor.Check)
    assert not check.ok
    assert check.detail.endswith("; 1 differ from its RECORD, first mcp_server/a.py")


def test_installed_wheel_reports_version_and_digest(monkeypatch, tmp_path):
    package, dist = _wheel_install(tmp_path)
    _imported_from(monkeypatch, package, dist)
    check = doctor_artifact.artifact_identity(doctor.Check)
    digest = doctor_artifact.members_digest([("mcp_server/a.py", X1)])
    assert (check.name, check.ok, check.optional) == (doctor_artifact.NAME, True, True)
    assert check.detail == (
        f"installed hypermnesia-mcp 9.9.9, 1 mcp_server members, digest {digest}"
    )


def test_installed_file_differing_from_record_fails(monkeypatch, tmp_path):
    package, dist = _wheel_install(tmp_path, tamper=True)
    _imported_from(monkeypatch, package, dist)
    check = doctor_artifact.artifact_identity(doctor.Check)
    assert (check.name, check.ok, check.optional) == (doctor_artifact.NAME, False, True)
    assert check.detail.startswith("installed hypermnesia-mcp 9.9.9, 1 mcp_server")
    assert check.detail.endswith("; 1 differ from its RECORD, first mcp_server/a.py")
    assert check.fix == (
        "Reinstall the runtime: `uv tool install --reinstall --no-build "
        '"hypermnesia-mcp[postgresql,sqlite]==9.9.9"` (Codex) or reinstall the '
        "plugin (Claude)"
    )


def test_wheel_installed_elsewhere_describes_the_imported_tree(monkeypatch, tmp_path):
    _, dist = _wheel_install(tmp_path)
    package = _source_package(tmp_path)
    _imported_from(monkeypatch, package, dist)
    _git_replies(monkeypatch, "abc123", "")
    check = doctor_artifact.artifact_identity(doctor.Check)
    assert check.detail.startswith(
        f"source tree {package.parent} at abc123 (version 9.9.9)"
    )


def test_source_tree_names_revision_and_changes(monkeypatch, tmp_path):
    package = _source_package(tmp_path)
    _without_distribution(monkeypatch, package)
    calls = _git_replies(monkeypatch, "abc123", " M mcp_server/a.py")
    check = doctor_artifact.artifact_identity(doctor.Check)
    digest = doctor_artifact.members_digest([("mcp_server/a.py", X1)])
    assert (check.name, check.ok, check.optional) == (doctor_artifact.NAME, True, True)
    assert check.detail == (
        f"source tree {package.parent} at abc123 with uncommitted changes "
        f"(version unknown), 1 mcp_server files, digest {digest}{SUFFIX}"
    )
    kwargs = {"cwd": package.parent, "timeout": 2.0}
    assert calls == [
        (["git", "rev-parse", "HEAD"], kwargs),
        (["git", "status", "--porcelain", "--", "mcp_server"], kwargs),
    ]


def test_source_tree_without_git_says_so(monkeypatch, tmp_path):
    package = _source_package(tmp_path)
    _without_distribution(monkeypatch, package)
    _git_replies(monkeypatch, None, None)
    check = doctor_artifact.artifact_identity(doctor.Check)
    assert check.detail.startswith(f"source tree {package.parent} at no git revision (")


def test_failed_git_status_is_not_a_clean_tree(monkeypatch, tmp_path):
    # rev-parse answers, status times out: the tree is not known to match it.
    package = _source_package(tmp_path)
    _without_distribution(monkeypatch, package)
    _git_replies(monkeypatch, "abc123", None)
    check = doctor_artifact.artifact_identity(doctor.Check)
    assert (check.name, check.ok, check.optional) == (doctor_artifact.NAME, False, True)
    assert "at abc123 (version unknown)" in check.detail
    assert check.detail.endswith(
        f"{SUFFIX}; revision state unknown: `git status` failed"
    )
    assert check.fix == (
        f"Run `git -C {package.parent} status` to see why git cannot answer"
    )


def test_unreadable_member_fails_the_check_only(monkeypatch, tmp_path):
    package, dist = _wheel_install(tmp_path)
    _imported_from(monkeypatch, package, dist)

    def denied(self):
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(doctor_artifact.Path, "read_bytes", denied)
    check = doctor_artifact.artifact_identity(doctor.Check)
    assert (check.name, check.ok, check.optional) == (doctor_artifact.NAME, False, True)
    assert check.detail == (
        "cannot read the running artifact: [Errno 13] Permission denied: "
        f"'{package / 'a.py'}'"
    )


def test_malformed_record_fails_the_check_only(monkeypatch, tmp_path):
    package, dist = _wheel_install(tmp_path)
    (dist._path / "RECORD").write_text("garbage\n")
    _imported_from(monkeypatch, package, dist)
    check = doctor_artifact.artifact_identity(doctor.Check)
    assert (check.name, check.ok, check.optional) == (doctor_artifact.NAME, False, True)
    assert check.detail.startswith("cannot read the running artifact: ")


def test_blank_record_lines_are_skipped(tmp_path):
    _, dist = _wheel_install(tmp_path)
    record = dist._path / "RECORD"
    record.write_text("\n" + record.read_text())
    assert doctor_artifact.wheel_members(dist) == [("mcp_server/a.py", X1)]


def test_editable_install_is_a_source_tree():
    # The dev environment installs hypermnesia-mcp editable: its RECORD lists
    # no mcp_server member, so the check must describe the checkout.
    check = doctor_artifact.artifact_identity(doctor.Check)
    assert check.detail.startswith("source tree ")


def test_both_backends_run_the_check():
    assert doctor._artifact_identity in doctor.CHECKS
    assert doctor._artifact_identity in doctor.SQLITE_CHECKS
    assert doctor._artifact_identity().name == doctor_artifact.NAME
