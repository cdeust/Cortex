"""The run MANIFEST names the ``mcp_server`` artifact behind its scores (#729)."""

from __future__ import annotations

from pathlib import Path

from benchmarks.lib import write_manifest
from benchmarks.lib.write_manifest import _artifact_fields
from mcp_server import doctor_artifact


def test_artifact_fields_carry_the_doctor_identity() -> None:
    fields = _artifact_fields()["runtime_artifact"]
    assert set(fields) == {"ok", "detail", "fix"}
    # The checkout under test is a source tree: revision and digest are named.
    assert "digest " in fields["detail"]


def test_altered_identity_is_recorded_not_raised(monkeypatch) -> None:
    def broken(check):
        return check(doctor_artifact.NAME, False, "2 differ", "reinstall")

    monkeypatch.setattr(doctor_artifact, "artifact_identity", broken)
    assert _artifact_fields() == {
        "runtime_artifact": {"ok": False, "detail": "2 differ", "fix": "reinstall"}
    }


def test_build_manifest_includes_runtime_artifact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(write_manifest, "_environment_fields", lambda: {})
    marker = {"runtime_artifact": {"ok": True, "detail": "d", "fix": None}}
    monkeypatch.setattr(write_manifest, "_artifact_fields", lambda: marker)
    manifest = write_manifest.build_manifest(
        str(tmp_path), "abc", "sha", "img", "box", "5432", "7"
    )
    assert manifest["runtime_artifact"] == marker["runtime_artifact"]
    assert manifest["git_sha"] == "abc"
