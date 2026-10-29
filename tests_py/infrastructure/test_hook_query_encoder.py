"""Issue #706: torch-free hook query encoder at the pinned model revision."""

import numpy as np
import pytest

from mcp_server.infrastructure import hook_query_encoder
from mcp_server.infrastructure.embedding_engine import EmbeddingEngine


def test_download_model_also_fetches_the_hook_encoder(monkeypatch):
    fetched = []
    monkeypatch.setattr(
        hook_query_encoder, "download_query_encoder", lambda: fetched.append(True)
    )
    engine = EmbeddingEngine()
    monkeypatch.setattr(engine, "_resolve_device", lambda: "cpu")
    monkeypatch.setattr(engine, "_construct_model", lambda *args, **kwargs: object())
    monkeypatch.setattr(engine, "_finalize_loaded", lambda device: None)
    engine.download_model()
    assert fetched == [True]


def test_absent_files_mean_no_encoder(monkeypatch):
    monkeypatch.setattr(hook_query_encoder, "_cached_paths", lambda: None)
    assert hook_query_encoder.cached_query_encoder() is None


def test_unloadable_files_mean_no_encoder(monkeypatch, caplog):
    monkeypatch.setattr(hook_query_encoder, "_cached_paths", lambda: ["t", "m"])

    def broken(*paths):
        raise OSError("truncated model file")

    monkeypatch.setattr(hook_query_encoder, "_build", broken)
    assert hook_query_encoder.cached_query_encoder() is None
    assert "hook query encoder unavailable" in caplog.text


def test_cached_encoder_reproduces_the_engine_space():
    encoder = hook_query_encoder.cached_query_encoder()
    if encoder is None:
        pytest.skip("pinned ONNX export not cached on this machine")
    engine = EmbeddingEngine()
    if engine.mode != "neural":
        pytest.skip("neural engine weights not cached on this machine")
    for text in ("Which drink can we brew?", "The pantry contains espresso beans."):
        stored = np.frombuffer(engine.encode(text) or b"", dtype=np.float32)
        query = encoder(text)
        agreement = float(query @ stored / np.linalg.norm(stored))
        # source: 0.99999997 measured on the parity fixture, 2026-10-29.
        assert agreement > 0.999
