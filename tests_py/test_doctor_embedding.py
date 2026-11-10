"""`cortex doctor` embedding weights identity check (issue #734, slice 4).

Each test builds the Hugging Face cache layout on disk (``blobs/<sha256>`` and
a snapshot link to it) and records the exact arguments the check passes to
the ``Check`` factory (mutation gate, ADR-1122).
"""

from __future__ import annotations

import hashlib
import os

import pytest

from mcp_server import doctor, doctor_embedding
from mcp_server.infrastructure import embedding_weights_cache
from mcp_server.infrastructure.embedding_model_lifecycle import DEFAULT_MODEL_REVISION

_NAME = "Embedding weights identity"
_REPO = "models--sentence-transformers--all-MiniLM-L6-v2"


def _record(*args, **kwargs):
    """A ``Check`` factory that returns what it was called with."""
    return args, kwargs


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor_embedding, "embedding_hub_cache", lambda: str(tmp_path))
    return str(tmp_path)


def _paths(cache: str) -> tuple[str, str]:
    repo = os.path.join(cache, _REPO)
    entry = os.path.join(repo, "snapshots", DEFAULT_MODEL_REVISION, "model.safetensors")
    return repo, entry


def _store(cache: str, data: bytes, blob: str) -> str:
    """Write ``data`` as blob ``blob`` and link the snapshot entry to it."""
    repo, entry = _paths(cache)
    os.makedirs(os.path.join(repo, "blobs"))
    os.makedirs(os.path.dirname(entry))
    with open(os.path.join(repo, "blobs", blob), "wb") as handle:
        handle.write(data)
    try:
        os.symlink(os.path.join("..", "..", "blobs", blob), entry)
    except OSError as exc:
        # huggingface_hub copies files where links are unsupported; that case
        # is test_a_copied_file_is_reported_unverifiable.
        pytest.skip(f"symlinks unavailable here: {exc}")
    return entry


def test_absent_weights_warn_and_say_how_they_arrive(cache):
    _, entry = _paths(cache)
    fix = (
        f"Run one recall with network access: the engine downloads revision "
        f"{DEFAULT_MODEL_REVISION} into {cache} in the background (not when "
        "CORTEX_EMBEDDING_ZERO_DOWNLOAD is set)"
    )
    detail = f"absent at {entry}; recall serves the fallback embedding"
    assert doctor_embedding.embedding_identity(_record) == (
        (_NAME, False, detail, fix),
        {"optional": True},
    )


def test_weights_matching_their_blob_name_pass(cache):
    digest = hashlib.sha256(b"weights").hexdigest()
    _store(cache, b"weights", digest)
    detail = f"sha256 {digest} matches the digest the Hub declared"
    assert doctor_embedding.embedding_identity(_record) == (
        (_NAME, True, detail, ""),
        {"optional": True},
    )


def test_altered_weights_warn_with_both_digests(cache):
    declared = hashlib.sha256(b"weights").hexdigest()
    entry = _store(cache, b"truncated", declared)
    found = hashlib.sha256(b"truncated").hexdigest()
    repo, _ = _paths(cache)
    detail = f"sha256 {found} at {entry} differs from the {declared} the Hub declared"
    fix = (
        f"Remove the directory {repo} and let the engine download the revision "
        "again; vectors written with this file are not comparable with the "
        "published numbers"
    )
    assert doctor_embedding.embedding_identity(_record) == (
        (_NAME, False, detail, fix),
        {"optional": True},
    )


def test_a_copied_file_is_reported_unverifiable(cache):
    _, entry = _paths(cache)
    os.makedirs(os.path.dirname(entry))
    with open(entry, "wb") as handle:
        handle.write(b"weights")
    digest = hashlib.sha256(b"weights").hexdigest()
    detail = (
        f"{entry} is a copy, not a link to a blob named by its digest; "
        f"its sha256 is {digest}"
    )
    assert doctor_embedding.embedding_identity(_record) == (
        (_NAME, False, detail, ""),
        {"optional": True},
    )


def test_unreadable_weights_warn_instead_of_raising(cache, monkeypatch):
    def denied(path):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr(doctor_embedding, "file_sha256", denied)
    _, entry = _paths(cache)
    error = PermissionError(13, "Permission denied", entry)
    detail = f"cannot read {entry}: PermissionError: {error}"
    assert doctor_embedding.embedding_identity(_record) == (
        (_NAME, False, detail, ""),
        {"optional": True},
    )


def test_the_check_runs_on_both_backends():
    assert doctor._embedding_identity in doctor.CHECKS
    assert doctor._embedding_identity in doctor.SQLITE_CHECKS


@pytest.mark.parametrize(
    ("env", "parts"),
    [
        ({}, ("~", ".cache", "huggingface", "hub")),
        ({"XDG_CACHE_HOME": "/x"}, ("/x", "huggingface", "hub")),
        ({"HF_HOME": "/h"}, ("/h", "hub")),
        ({"HF_HOME": "/h", "HUGGINGFACE_HUB_CACHE": "/legacy"}, ("/legacy",)),
        ({"HUGGINGFACE_HUB_CACHE": "/legacy", "HF_HUB_CACHE": "/new"}, ("/new",)),
    ],
)
def test_hub_cache_follows_huggingface_hub_resolution(monkeypatch, env, parts):
    for name in ("XDG_CACHE_HOME", "HF_HOME", "HUGGINGFACE_HUB_CACHE", "HF_HUB_CACHE"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    expected = os.path.expanduser(os.path.join(*parts))
    assert embedding_weights_cache._hf_hub_cache() == expected


def test_engine_cache_folder_wins_then_sentence_transformers_home(monkeypatch):
    monkeypatch.setattr(
        embedding_weights_cache, "embedding_cache_dir", lambda: "/cortex"
    )
    assert embedding_weights_cache.embedding_hub_cache() == os.path.realpath("/cortex")
    monkeypatch.setattr(embedding_weights_cache, "embedding_cache_dir", lambda: None)
    monkeypatch.setenv("SENTENCE_TRANSFORMERS_HOME", "/st")
    assert embedding_weights_cache.embedding_hub_cache() == os.path.realpath("/st")


def test_a_home_relative_cache_is_expanded_as_the_loader_does(monkeypatch):
    # hf_hub_download (1.33.0) loads from Path(cache_dir).expanduser().resolve().
    monkeypatch.setattr(embedding_weights_cache, "embedding_cache_dir", lambda: None)
    monkeypatch.setenv("SENTENCE_TRANSFORMERS_HOME", os.path.join("~", "models"))
    expected = os.path.realpath(os.path.join(os.path.expanduser("~"), "models"))
    assert embedding_weights_cache.embedding_hub_cache() == expected
