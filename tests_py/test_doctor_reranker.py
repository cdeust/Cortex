"""`cortex doctor` reranker weights identity check (issue #734, slice 3)."""

from __future__ import annotations

import functools
import hashlib

import pytest

from mcp_server import doctor, doctor_reranker
from mcp_server.core.reranker_identity import classify_model_digest


@pytest.fixture
def weights(tmp_path, monkeypatch):
    """A cache directory the check reads, and the weights path inside it."""
    monkeypatch.setattr(doctor_reranker, "reranker_cache_dir", lambda: str(tmp_path))
    path = tmp_path / "ms-marco-MiniLM-L-12-v2" / "flashrank-MiniLM-L-12-v2_Q.onnx"
    path.parent.mkdir()
    return path


def _pin(monkeypatch, data: bytes) -> None:
    pinned = functools.partial(
        classify_model_digest, expected=hashlib.sha256(data).hexdigest()
    )
    monkeypatch.setattr(doctor_reranker, "classify_model_digest", pinned)


def test_absent_weights_warn_with_the_path(weights):
    check = doctor_reranker.reranker_identity(doctor.Check)
    assert (check.ok, check.optional) == (False, True)
    assert str(weights) in check.detail
    assert "CORTEX_RERANKER_OFFLINE" in check.fix


def test_pinned_weights_pass(weights, monkeypatch):
    weights.write_bytes(b"pinned weights")
    _pin(monkeypatch, b"pinned weights")
    check = doctor_reranker.reranker_identity(doctor.Check)
    assert check.ok
    assert hashlib.sha256(b"pinned weights").hexdigest() in check.detail


def test_different_weights_warn_with_both_digests(weights, monkeypatch):
    weights.write_bytes(b"other weights")
    _pin(monkeypatch, b"pinned weights")
    check = doctor_reranker.reranker_identity(doctor.Check)
    assert (check.ok, check.optional) == (False, True)
    assert hashlib.sha256(b"other weights").hexdigest() in check.detail
    assert hashlib.sha256(b"pinned weights").hexdigest() in check.detail
    assert str(weights) in check.fix


def test_unreadable_weights_warn_instead_of_raising(weights, monkeypatch):
    def denied(path):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(doctor_reranker, "reranker_model_sha256", denied)
    check = doctor_reranker.reranker_identity(doctor.Check)
    assert (check.ok, check.optional) == (False, True)
    assert "PermissionError" in check.detail


def test_the_check_runs_on_both_backends():
    assert doctor._reranker_identity in doctor.CHECKS
    assert doctor._reranker_identity in doctor.SQLITE_CHECKS
