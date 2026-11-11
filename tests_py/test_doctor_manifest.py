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
from mcp_server.core import reranker_model
from mcp_server.core.reranker_identity import EXPECTED_MODEL_SHA256
from mcp_server.doctor_artifact import Identity
from mcp_server.infrastructure.backend_marker import BackendMarkerError
from mcp_server.infrastructure.embedding_model_lifecycle import DEFAULT_MODEL_REVISION

_OTHER = "0" * 64


@pytest.fixture
def caches(tmp_path, monkeypatch):
    """Empty embedding and reranker caches under ``tmp_path``."""
    hub, flashrank = tmp_path / "hub", tmp_path / "flashrank"
    monkeypatch.setattr(doctor_manifest, "embedding_hub_cache", lambda: str(hub))
    monkeypatch.setattr(reranker_model, "reranker_cache_dir", lambda: str(flashrank))
    return tmp_path


def test_empty_caches_give_absent_weights_and_no_served_model(caches):
    manifest = doctor_manifest.effective_manifest()
    assert list(manifest) == ["schema", "artifact", "backend", "embedding", "reranker"]
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


@pytest.mark.parametrize(
    ("modified", "altered", "expected"),
    [(False, (), False), (True, (), True), (False, ("mcp_server/x.pyc",), True)],
)
def test_the_artifact_section_states_every_field(
    tmp_path, monkeypatch, modified, altered, expected
):
    # Bytecode that runs other code counts as modified, like a changed member.
    found = Identity(
        "wheel", "4.24.0", None, modified, (), tmp_path, altered=altered,
        unknown="why",
    )  # fmt: skip
    monkeypatch.setattr(doctor_manifest, "identify", lambda: found)
    assert doctor_manifest.artifact_section() == {
        "kind": "wheel",
        "version": "4.24.0",
        "revision": None,
        "modified": expected,
        "digest": found.digest,
        "unknown": "why",
    }


def test_linked_embedding_weights_are_verified(caches, monkeypatch):
    digest = "a" * 64
    monkeypatch.setattr(doctor_manifest, "linked_blob_name", lambda _p: digest)
    monkeypatch.setattr(doctor_manifest, "file_sha256", lambda _p: digest)
    weights = doctor_manifest.embedding_section(None)["weights"]
    assert weights == {"state": "verified", "sha256": digest}


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


def test_the_subcommand_prints_indented_json(monkeypatch, capsys):
    # Two-space indentation: the document is read by people as well as tools.
    monkeypatch.setattr(doctor, "effective_manifest", lambda: {"a": {"b": 1}})
    monkeypatch.setattr(doctor.sys, "argv", ["cortex-doctor", "manifest"])
    assert doctor.run() == 0
    assert capsys.readouterr().out == '{\n  "a": {\n    "b": 1\n  }\n}\n'


def test_the_written_manifest_embeds_what_the_run_served(caches, monkeypatch):
    embedding, reranker = {"embedding_mode": "e"}, {"reranker_state": "r"}
    monkeypatch.setattr(write_manifest, "embedding_manifest_fields", lambda: embedding)
    monkeypatch.setattr(write_manifest, "reranker_fields", lambda: reranker)
    runtime = write_manifest._environment_fields()["runtime_manifest"]
    assert runtime["embedding"]["served"] == embedding
    assert runtime["reranker"]["served"] == reranker


class _Engine:
    device_requested = "cuda"


def test_the_repro_manifest_fills_the_served_embedding(caches, monkeypatch):
    # The benchmark engine, not the factory setting, says which device ran.
    monkeypatch.setenv("CORTEX_MEMORY_EMBEDDING_DEVICE", "mps")
    reranker = {"reranker_state": "r", "reranker_model_path": str(caches / "m")}
    monkeypatch.setattr(_repro, "_reranker_manifest_fields", lambda: reranker)
    fields = {"embedding_mode": "neural"}
    monkeypatch.setattr(_repro, "embedding_identity_fields", lambda _engine: fields)
    repro = _repro.build_repro_manifest()
    runtime = repro["runtime_manifest"]
    assert runtime["reranker"]["served"] == {"reranker_state": "r"}
    assert str(caches) not in json.dumps(runtime)
    assert runtime["embedding"]["served"] is None
    assert runtime["embedding"]["device_requested"] is None
    _repro.record_embedding_identity(repro, _Engine())
    assert runtime["embedding"]["served"] == fields
    assert runtime["embedding"]["device_requested"] == "cuda"


def test_benchmark_manifests_name_the_store_they_open(caches, monkeypatch):
    # The operator's selection is not what BenchmarkDB opens (PgMemoryStore).
    monkeypatch.setenv("CORTEX_MEMORY_STORE_BACKEND", "sqlite")
    monkeypatch.setattr(write_manifest, "embedding_manifest_fields", dict)
    monkeypatch.setattr(write_manifest, "reranker_fields", dict)
    monkeypatch.setattr(_repro, "_reranker_manifest_fields", dict)
    written = write_manifest._environment_fields()["runtime_manifest"]
    assert written["backend"] == "postgresql"
    assert _repro.build_repro_manifest()["runtime_manifest"]["backend"] == "postgresql"
    assert doctor_manifest.effective_manifest()["backend"] == "sqlite"


def test_the_matrix_cache_seam_is_the_one_hashed(caches, monkeypatch):
    # benchmarks/reranker_matrix patches the core seam to a cell's cache.
    cell = caches / "cell"
    monkeypatch.setattr(reranker_model, "reranker_cache_dir", lambda: str(cell))
    seen = []
    monkeypatch.setattr(doctor_manifest, "reranker_model_sha256", seen.append)
    doctor_manifest.reranker_section(None)
    assert seen == [reranker_model.model_path_under(str(cell))]


def test_the_engine_reports_its_requested_device():
    from mcp_server.infrastructure.embedding_engine import EmbeddingEngine

    assert EmbeddingEngine(device="mps").device_requested == "mps"
    assert EmbeddingEngine().device_requested == "cpu"


def test_the_engine_reports_the_device_its_model_runs_on(monkeypatch):
    # "auto" is a request; the manifest needs the device that was resolved,
    # and the CPU one after a GPU failure reloads the model (#734, slice 7).
    from mcp_server.infrastructure.embedding_engine import EmbeddingEngine

    engine = EmbeddingEngine(device="auto")
    assert engine.device_served is None  # no model loaded, no device served
    monkeypatch.setattr(EmbeddingEngine, "_detect_device", staticmethod(lambda: "mps"))
    engine._resolve_device()
    engine._model = object()
    assert (engine.device_requested, engine.device_served) == ("auto", "mps")

    def reload_on(device_engine=engine):
        device_engine._model = object()

    monkeypatch.setattr(engine, "_ensure_model", reload_on)
    engine._fallback_to_cpu()
    assert engine.device_served == "cpu"
    engine._model = None
    assert engine.device_served is None
