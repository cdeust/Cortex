"""Manifests record the embedding the run served, not the configured pin (#734)."""

from __future__ import annotations

import enum

from benchmarks import _repro
from benchmarks.lib import write_manifest
from benchmarks.lib.embedding_identity import (
    embedding_identity_fields,
    embedding_manifest_fields,
)
from mcp_server.infrastructure import embedding_factory
from mcp_server.infrastructure.embedding_model_lifecycle import ModelState

PIN = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
FIELDS = {
    "embedding_mode",
    "embedding_model_state",
    "embedding_model_name",
    "embedding_model_revision",
}


class _Engine:
    """Stand-in whose state settles only once ``mode`` is read, like the engine."""

    def __init__(self, settled: ModelState, mode: str) -> None:
        self._settled, self._mode = settled, mode
        self.model_state: enum.Enum = ModelState.UNINITIALIZED
        self.model_name, self.revision = "all-MiniLM-L6-v2", PIN

    @property
    def mode(self) -> str:
        self.model_state = self._settled
        return self._mode


def test_a_loaded_model_names_its_revision() -> None:
    fields = embedding_identity_fields(_Engine(ModelState.LOADED, "neural"))
    assert fields == {
        "embedding_mode": "neural",
        "embedding_model_state": "LOADED",
        "embedding_model_name": "all-MiniLM-L6-v2",
        "embedding_model_revision": PIN,
    }


def test_a_fallback_run_records_no_revision() -> None:
    # The probe of docs/audits/model-identity-inventory-2026-11-06.md: the
    # engine is PACKAGE_ABSENT and the old field still said PIN.
    for state in (
        ModelState.PACKAGE_ABSENT,
        ModelState.MODEL_FILES_ABSENT,
        ModelState.LOAD_RAISED,
    ):
        fields = embedding_identity_fields(_Engine(state, "fallback"))
        assert fields["embedding_mode"] == "fallback"
        assert fields["embedding_model_state"] == state.name
        assert fields["embedding_model_revision"] is None


def test_an_engine_that_cannot_be_built_is_unresolved(monkeypatch) -> None:
    def broken():
        raise RuntimeError("no engine")

    monkeypatch.setattr(embedding_factory, "get_embedding_engine", broken)
    assert embedding_manifest_fields() == {
        "embedding_mode": "unresolved",
        "embedding_model_state": "unresolved",
        "embedding_model_name": None,
        "embedding_model_revision": None,
    }


def test_the_process_engine_reports_a_consistent_identity() -> None:
    fields = embedding_manifest_fields()
    loaded = fields["embedding_model_state"] == "LOADED"
    assert fields["embedding_mode"] == ("neural" if loaded else "fallback")
    assert (fields["embedding_model_revision"] is not None) is loaded


def test_both_manifests_carry_the_served_identity(monkeypatch) -> None:
    marker = dict.fromkeys(FIELDS, "m")
    monkeypatch.setattr(write_manifest, "embedding_manifest_fields", lambda: marker)
    monkeypatch.setattr(_repro, "embedding_manifest_fields", lambda: marker)
    monkeypatch.setattr(write_manifest, "reranker_fields", lambda: {})
    monkeypatch.setattr(_repro, "_reranker_manifest_fields", lambda: {})
    for manifest in (
        write_manifest._environment_fields(),
        _repro.build_repro_manifest(),
    ):
        assert {k: manifest[k] for k in FIELDS} == marker
