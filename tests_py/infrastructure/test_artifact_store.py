"""Tests for the content-addressed artifact store (infrastructure, I/O)."""

from __future__ import annotations

from datetime import datetime, timezone

import mcp_server.infrastructure.artifact_store as artifact_store


def _patch_dir(tmp_path, monkeypatch):
    """Point ARTIFACTS_DIR at a tmp_path-backed directory."""
    target = tmp_path / "artifacts"
    monkeypatch.setattr(artifact_store, "ARTIFACTS_DIR", target)
    return target


def test_writes_and_returns_path(tmp_path, monkeypatch):
    root = _patch_dir(tmp_path, monkeypatch)
    content = "hello artifact world"
    path = artifact_store.store_artifact(content)
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == content
    assert root in path.parents


def test_content_addressing_same_content_same_path(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    when = datetime(2026, 6, 10, tzinfo=timezone.utc)
    p1 = artifact_store.store_artifact("identical payload", created_at=when)
    p2 = artifact_store.store_artifact("identical payload", created_at=when)
    assert p1 == p2


def test_dedup_does_not_rewrite(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    when = datetime(2026, 6, 10, tzinfo=timezone.utc)
    p1 = artifact_store.store_artifact("dedup me", created_at=when)
    mtime_before = p1.stat().st_mtime_ns
    # Tamper with the file; a second store of identical content must NOT
    # overwrite it (content addressing guarantees the bytes are equal anyway,
    # but we verify the dedup short-circuit by leaving the tampered file).
    p1.write_text("tampered", encoding="utf-8")
    p2 = artifact_store.store_artifact("dedup me", created_at=when)
    assert p2 == p1
    assert p2.read_text(encoding="utf-8") == "tampered"
    assert p2.stat().st_mtime_ns >= mtime_before


def test_monthly_sharding(tmp_path, monkeypatch):
    root = _patch_dir(tmp_path, monkeypatch)
    when = datetime(2026, 6, 10, tzinfo=timezone.utc)
    path = artifact_store.store_artifact("sharded content", created_at=when)
    assert path.parent == root / "2026-06"


def test_different_content_different_path(tmp_path, monkeypatch):
    _patch_dir(tmp_path, monkeypatch)
    when = datetime(2026, 6, 10, tzinfo=timezone.utc)
    p1 = artifact_store.store_artifact("content A", created_at=when)
    p2 = artifact_store.store_artifact("content B", created_at=when)
    assert p1 != p2


def test_write_artifact_reports_whether_it_created_the_file(tmp_path, monkeypatch):
    """Only the first writer of a content owns it (issue #737)."""
    _patch_dir(tmp_path, monkeypatch)
    when = datetime(2026, 11, 6, tzinfo=timezone.utc)
    p1, created1 = artifact_store.write_artifact("owned once", created_at=when)
    p2, created2 = artifact_store.write_artifact("owned once", created_at=when)
    assert created1 is True
    assert created2 is False
    assert p1 == p2


def test_discard_created_artifact_removes_it_and_tolerates_absence(
    tmp_path, monkeypatch
):
    _patch_dir(tmp_path, monkeypatch)
    path, created = artifact_store.write_artifact("to be discarded")
    assert created is True
    artifact_store.discard_created_artifact(path)
    assert not path.exists()
    artifact_store.discard_created_artifact(path)
