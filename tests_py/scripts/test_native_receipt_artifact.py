"""Tests for scripts/native_receipt_artifact.py, the artifact producer (#730)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_server import doctor_artifact
from mcp_server.doctor_artifact import Identity, members_digest
from scripts import native_receipt as nr
from scripts import native_receipt_artifact as producer
from tests_py.test_doctor_artifact import (
    X1,
    _git_replies,
    _imported_from,
    _source_package,
    _wheel_install,
    _without_distribution,
)

MEMBERS = (("mcp_server/a.py", "sha256=x"), ("mcp_server/b.py", "sha256=y"))
ROOT = Path("/opt/site-packages/mcp_server")


def _wheel(**changes) -> Identity:
    fields = dict(
        kind="wheel",
        version="4.23.5",
        revision=None,
        modified=False,
        members=MEMBERS,
        location=ROOT,
    )
    fields.update(changes)
    return Identity(**fields)


def _receipt(artifact: dict) -> dict:
    digest = artifact["members_digest"]
    return {
        "schema": nr.SCHEMA,
        "artifact": artifact,
        "platform": {"os": "macOS", "os_version": "26.1", "arch": "arm64"},
        "backend": "SQLite",
        "hosts": [{"name": "claude-code", "version": "2.1.0"}],
        "checks": [
            {
                "id": "capture",
                "host": "claude-code",
                "outcome": "passed",
                "artifact_digest": digest,
                "evidence": "transcript line 12",
            }
        ],
    }


def test_a_clean_wheel_is_distributed_evidence():
    artifact = producer.receipt_artifact(_wheel())
    assert artifact == {
        "kind": "wheel",
        "version": "4.23.5",
        "revision": None,
        "modified": False,
        "members_digest": members_digest(MEMBERS),
    }
    receipt = _receipt(artifact)
    assert nr.validate(receipt) == []
    assert nr.is_distributed(receipt)


def test_a_wheel_differing_from_its_record_is_refused():
    # Codex review on #957: the digest of an altered wheel is its RECORD's, so
    # two differently altered installs would share it; no receipt binds to it.
    found = _wheel(modified=True, altered=("mcp_server/a.py",), fix="reinstall")
    with pytest.raises(producer.UnstatedIdentityError, match="differs from its RECORD"):
        producer.receipt_artifact(found)


def test_a_checkout_carries_its_revision_and_changes():
    found = _wheel(kind="source-tree", revision="abc123", modified=True, in_git=True)
    artifact = producer.receipt_artifact(found)
    assert (artifact["revision"], artifact["modified"]) == ("abc123", True)
    assert nr.validate(_receipt(artifact)) == []


def test_a_tree_outside_git_has_a_null_revision():
    artifact = producer.receipt_artifact(_wheel(kind="source-tree"))
    assert (artifact["kind"], artifact["revision"]) == ("source-tree", None)
    assert nr.validate(_receipt(artifact)) == []


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        (
            {"kind": "source-tree", "in_git": True, "revision": "abc123",
             "unknown": "revision state unknown: `git status` failed"},
            "revision state unknown",
        ),
        ({"members": (), "unknown": "installed x has no RECORD"}, "no RECORD"),
        ({"kind": "source-tree", "version": None}, "names the version"),
        ({"kind": "source-tree", "in_git": True}, "no commit"),
    ],
)  # fmt: skip
def test_an_unstated_identity_is_refused(changes, reason):
    with pytest.raises(producer.UnstatedIdentityError, match=reason):
        producer.receipt_artifact(_wheel(**changes))


def test_main_prints_the_artifact_object(monkeypatch, capsys):
    monkeypatch.setattr(producer, "identify", _wheel)
    assert producer.main() == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["members_digest"] == members_digest(MEMBERS)


def test_main_refuses_without_printing_a_field(monkeypatch, capsys):
    monkeypatch.setattr(producer, "identify", lambda: _wheel(version=None))
    assert producer.main() == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "cannot state the running artifact" in out.err


def test_an_installed_wheel_produces_a_valid_receipt_artifact(monkeypatch, tmp_path):
    # End to end through identify(): the fixture wheel of the doctor's tests.
    package, dist = _wheel_install(tmp_path)
    _imported_from(monkeypatch, package, dist)
    artifact = producer.receipt_artifact(doctor_artifact.identify())
    assert artifact == {
        "kind": "wheel",
        "version": "9.9.9",
        "revision": None,
        "modified": False,
        "members_digest": members_digest([("mcp_server/a.py", X1)]),
    }


def test_a_tampered_wheel_is_refused(monkeypatch, tmp_path):
    package, dist = _wheel_install(tmp_path, tamper=True)
    _imported_from(monkeypatch, package, dist)
    found = doctor_artifact.identify()
    assert (found.modified, found.altered) == (True, ("mcp_server/a.py",))
    with pytest.raises(producer.UnstatedIdentityError, match="reinstall it"):
        producer.receipt_artifact(found)


def test_a_checkout_without_an_installed_version_is_refused(monkeypatch, tmp_path):
    package = _source_package(tmp_path)
    _without_distribution(monkeypatch, package)
    _git_replies(monkeypatch, "abc123", "")
    found = doctor_artifact.identify()
    assert (found.kind, found.revision, found.modified) == (
        "source-tree",
        "abc123",
        False,
    )
    with pytest.raises(producer.UnstatedIdentityError, match="names the version"):
        producer.receipt_artifact(found)
