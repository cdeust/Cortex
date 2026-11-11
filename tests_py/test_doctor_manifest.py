"""One effective runtime manifest for doctor and benchmarks (issue #734, slice 5).

The caches are pointed at ``tmp_path`` so every state is built on disk or
injected at the one seam that reads it; each test asserts exact values
(mutation gate, ADR-1122).
"""

from __future__ import annotations

import json

import pytest

from benchmarks import _repro
from benchmarks.lib import write_manifest
from mcp_server import doctor, doctor_manifest
from mcp_server.core.reranker_identity import EXPECTED_MODEL_SHA256
from mcp_server.infrastructure.backend_marker import BackendMarkerError
from mcp_server.infrastructure.embedding_model_lifecycle import DEFAULT_MODEL_REVISION

_OTHER = "0" * 64


@pytest.fixture
def caches(tmp_path, monkeypatch):
    """Empty embedding and reranker caches under ``tmp_path``."""
    hub, flashrank = tmp_path / "hub", tmp_path / "flashrank"
    monkeypatch.setattr(doctor_manifest, "embedding_hub_cache", lambda: str(hub))
    monkeypatch.setattr(doctor_manifest, "reranker_cache_dir", lambda: str(flashrank))
    return tmp_path


def test_empty_caches_give_absent_weights_and_no_served_model(caches):
    manifest = doctor_manifest.effective_manifest()
    assert manifest["schema"] == 1
    assert manifest["embedding"] == {
        "name": "all-MiniLM-L6-v2",
        "pinned_revision": DEFAULT_MODEL_REVISION,
        "device_requested": "cpu",
        "weights": {"state": "absent", "sha256": None},
        "served": None,
    }
    assert manifest["reranker"] == {
        "name": "ms-marco-MiniLM-L-12-v2",
        "file": "flashrank-MiniLM-L-12-v2_Q.onnx",
        "expected_sha256": EXPECTED_MODEL_SHA256,
        "weights": {"state": "absent", "sha256": None},
        "served": None,
    }


def test_the_manifest_names_no_path(caches):
    # A cache path names the user's home directory: only states and digests.
    text = json.dumps(doctor_manifest.effective_manifest())
    assert str(caches) not in text
    assert str(doctor_manifest.identify().location) not in text


@pytest.mark.parametrize(
    ("digest", "state"), [(EXPECTED_MODEL_SHA256, "verified"), (_OTHER, "mismatch")]
)
def test_reranker_digest_is_classified_against_the_pin(
    caches, monkeypatch, digest, state
):
    monkeypatch.setattr(doctor_manifest, "reranker_model_sha256", lambda _p: digest)
    weights = doctor_manifest.reranker_section(None)["weights"]
    assert weights == {"state": state, "sha256": digest}


def test_unreadable_weights_name_the_error_class_only(caches, monkeypatch):
    def denied(path):
        raise PermissionError(13, "denied", path)

    monkeypatch.setattr(doctor_manifest, "file_sha256", denied)
    monkeypatch.setattr(doctor_manifest, "reranker_model_sha256", denied)
    expected = {"state": "unreadable: PermissionError", "sha256": None}
    assert doctor_manifest.embedding_section(None)["weights"] == expected
    assert doctor_manifest.reranker_section(None)["weights"] == expected


@pytest.mark.parametrize(
    ("value", "backend"),
    [("sqlite", "sqlite"), ("postgresql", "postgresql"), ("auto", "auto")],
)
def test_backend_is_the_selected_one(monkeypatch, value, backend):
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", value)
    assert doctor_manifest.backend_section() == backend


def test_a_corrupt_marker_is_reported_not_guessed(monkeypatch):
    def corrupt(_environ):
        raise BackendMarkerError("bad marker at /home/someone")

    monkeypatch.setattr(doctor_manifest, "effective_backend", corrupt)
    assert doctor_manifest.backend_section() == "unreadable: BackendMarkerError"


def test_an_unreadable_artifact_is_reported(monkeypatch):
    def loop():
        raise RuntimeError("symlink loop at /home/someone")

    monkeypatch.setattr(doctor_manifest, "identify", loop)
    assert doctor_manifest.artifact_section() == {
        "kind": None,
        "unknown": "unreadable: RuntimeError",
    }


def test_the_artifact_section_is_the_doctor_identity():
    found = doctor_manifest.identify()
    section = doctor_manifest.artifact_section()
    assert section["kind"] == found.kind
    assert section["digest"] == found.digest
    assert section["revision"] == found.revision


def test_served_fields_are_carried_as_given(caches):
    embedding, reranker = {"embedding_mode": "neural"}, {"reranker_state": "loaded"}
    manifest = doctor_manifest.effective_manifest(embedding, reranker)
    assert manifest["embedding"]["served"] == embedding
    assert manifest["reranker"]["served"] == reranker


def test_doctor_manifest_subcommand_prints_it(caches, monkeypatch, capsys):
    monkeypatch.setattr(doctor.sys, "argv", ["cortex-doctor", "manifest"])
    assert doctor.run() == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["schema"] == 1
    assert printed["embedding"]["weights"]["state"] == "absent"


def test_the_written_manifest_embeds_what_the_run_served(caches, monkeypatch):
    embedding, reranker = {"embedding_mode": "e"}, {"reranker_state": "r"}
    monkeypatch.setattr(write_manifest, "embedding_manifest_fields", lambda: embedding)
    monkeypatch.setattr(write_manifest, "reranker_fields", lambda: reranker)
    runtime = write_manifest._environment_fields()["runtime_manifest"]
    assert runtime["embedding"]["served"] == embedding
    assert runtime["reranker"]["served"] == reranker


def test_the_repro_manifest_fills_the_served_embedding(caches, monkeypatch):
    reranker = {"reranker_state": "r"}
    monkeypatch.setattr(_repro, "_reranker_manifest_fields", lambda: reranker)
    fields = {"embedding_mode": "neural"}
    monkeypatch.setattr(_repro, "embedding_identity_fields", lambda _engine: fields)
    repro = _repro.build_repro_manifest()
    assert repro["runtime_manifest"]["reranker"]["served"] == reranker
    assert repro["runtime_manifest"]["embedding"]["served"] is None
    _repro.record_embedding_identity(repro, object())
    assert repro["runtime_manifest"]["embedding"]["served"] == fields
