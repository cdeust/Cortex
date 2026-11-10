"""`cortex doctor` reranker weights identity check (issue #734, slice 3).

Each test records the exact arguments the check passes to the ``Check``
factory, so a changed name, detail, fix or ``optional`` flag fails a test
(mutation gate, ADR-1122).
"""

from __future__ import annotations

import functools
import hashlib

import pytest

from mcp_server import doctor, doctor_reranker
from mcp_server.core.reranker_identity import classify_model_digest

_NAME = "Reranker weights identity"
_MODEL = "ms-marco-MiniLM-L-12-v2"
_FILE = "flashrank-MiniLM-L-12-v2_Q.onnx"


def _record(*args, **kwargs):
    """A ``Check`` factory that returns what it was called with."""
    return args, kwargs


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """The cache directory the check reads, spelled as production joins it."""
    monkeypatch.setattr(doctor_reranker, "reranker_cache_dir", lambda: str(tmp_path))
    (tmp_path / _MODEL).mkdir()
    return str(tmp_path)


def _pin(monkeypatch, data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()
    pinned = functools.partial(classify_model_digest, expected=digest)
    monkeypatch.setattr(doctor_reranker, "classify_model_digest", pinned)
    return digest


def _write(cache: str, data: bytes) -> None:
    with open(f"{cache}/{_MODEL}/{_FILE}", "wb") as handle:
        handle.write(data)


def test_absent_weights_warn_and_name_the_directory_to_remove(cache):
    path, model_dir = f"{cache}/{_MODEL}/{_FILE}", f"{cache}/{_MODEL}"
    detail = f"absent at {path}; recall runs without reranking"
    fix = (
        f"Remove {model_dir} if it exists, then run one recall with network "
        "access (FlashRank downloads the model into this cache), or provision "
        "the whole directory there before setting CORTEX_RERANKER_OFFLINE"
    )
    assert doctor_reranker.reranker_identity(_record) == (
        (_NAME, False, detail, fix),
        {"optional": True},
    )


def test_pinned_weights_pass(cache, monkeypatch):
    _write(cache, b"pinned weights")
    digest = _pin(monkeypatch, b"pinned weights")
    detail = f"sha256 {digest} matches the published results"
    assert doctor_reranker.reranker_identity(_record) == (
        (_NAME, True, detail, ""),
        {"optional": True},
    )


def test_different_weights_warn_with_both_digests(cache, monkeypatch):
    _write(cache, b"other weights")
    expected = _pin(monkeypatch, b"pinned weights")
    found = hashlib.sha256(b"other weights").hexdigest()
    path, model_dir = f"{cache}/{_MODEL}/{_FILE}", f"{cache}/{_MODEL}"
    detail = f"sha256 {found} at {path} differs from the expected {expected}"
    # FlashRank re-downloads only when the model directory is absent.
    fix = (
        f"Remove the directory {model_dir} and let FlashRank download it again; "
        "results measured with this file are not comparable with the published "
        "numbers"
    )
    assert doctor_reranker.reranker_identity(_record) == (
        (_NAME, False, detail, fix),
        {"optional": True},
    )


def test_unreadable_weights_warn_instead_of_raising(cache, monkeypatch):
    def denied(path):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(doctor_reranker, "reranker_model_sha256", denied)
    path = f"{cache}/{_MODEL}/{_FILE}"
    error = PermissionError(13, "Permission denied", path)
    detail = f"cannot read {path}: PermissionError: {error}"
    assert doctor_reranker.reranker_identity(_record) == (
        (_NAME, False, detail, ""),
        {"optional": True},
    )


def test_the_check_runs_on_both_backends():
    assert doctor._reranker_identity in doctor.CHECKS
    assert doctor._reranker_identity in doctor.SQLITE_CHECKS
