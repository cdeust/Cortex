"""Shared first-launch policy, issues #703/#704; preserve ADR-1104 and ADR-1114."""

import json

import pytest

from mcp_server.infrastructure import backend_marker, backend_resolution, managed_pg


def test_first_decision_uses_the_supplied_environment(tmp_path, monkeypatch):
    (tmp_path / "session-log.json").write_text("{}")
    monkeypatch.setenv("PGSERVICE", "must-not-leak-into-the-decision")
    seen = []

    def legacy(environ):
        seen.append(environ)
        return True, "all refused"

    monkeypatch.setattr(backend_resolution, "legacy_store_answer", legacy)
    assert backend_resolution.decide(tmp_path, "backend.json", {})[0] == "sqlite"
    assert seen == [{}]


@pytest.mark.parametrize("key", ["DATABASE_URL", "CORTEX_MEMORY_DATABASE_URL"])
def test_explicit_url_bypasses_invalid_marker_and_stays_explicit(tmp_path, key):
    marker = tmp_path / "backend.json"
    marker.write_text("invalid")
    env = {key: "postgresql:///operator_db"}
    assert backend_resolution.settle_backend(env, marker) == ""
    assert env["DATABASE_URL"] == "postgresql:///operator_db"
    assert marker.read_text() == "invalid"


def test_managed_marker_uses_existing_attachment_and_is_not_rewritten(
    tmp_path, monkeypatch
):
    marker = tmp_path / "backend.json"
    record = {"backend": "managed", "root": str(tmp_path / "managed-pg")}
    marker.write_text(json.dumps(record))
    attached = []

    def use(paths, environ):
        attached.append(paths.root)
        additions = {
            "CORTEX_MEMORY_STORE_BACKEND": "postgresql",
            "DATABASE_URL": "managed-dsn",
        }
        environ.update(additions)
        return additions

    monkeypatch.setattr(managed_pg, "use", use)
    env = {}
    assert backend_resolution.settle_backend(env, marker) == "postgresql"
    assert attached == [tmp_path / "managed-pg"]
    assert env["DATABASE_URL"] == "managed-dsn"
    assert json.loads(marker.read_text()) == record


def test_invalid_marker_is_an_error_without_a_guessed_backend(tmp_path):
    marker = tmp_path / "backend.json"
    marker.write_text("invalid")
    env = {}
    with pytest.raises(backend_marker.BackendMarkerError):
        backend_resolution.settle_backend(env, marker)
    assert env == {}


def test_first_decision_write_failure_propagates(tmp_path, monkeypatch):
    def cannot_write(*args):
        raise OSError("read-only marker directory")

    monkeypatch.setattr(backend_marker, "write_backend_marker", cannot_write)
    with pytest.raises(OSError, match="read-only marker directory"):
        backend_resolution.settle_backend({}, tmp_path / "backend.json")


def test_explicit_auto_remains_an_operator_choice(tmp_path):
    marker = tmp_path / "backend.json"
    env = {"CORTEX_MEMORY_STORE_BACKEND": "auto"}
    assert backend_resolution.settle_backend(env, marker) == "auto"
    assert not marker.exists()
    assert "DATABASE_URL" not in env
