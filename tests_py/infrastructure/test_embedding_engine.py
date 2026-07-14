"""Tests for mcp_server.infrastructure.embedding_engine — text embedding."""

from __future__ import annotations

from collections import OrderedDict
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from mcp_server.infrastructure.embedding_engine import (
    DEFAULT_MODEL_REVISION,
    EmbeddingEngine,
    embedding_cache_dir,
    get_embedding_engine,
    reset_embedding_engine,
)


# ── Cache folder (issue #124 — align with reranker's bb1c581f hardening) ──


class TestEmbeddingCacheDir:
    """Mirrors TestRerankerCacheDir in tests_py/core/test_reranker.py."""

    def test_default_is_not_tmp(self, monkeypatch):
        monkeypatch.delenv("HF_HOME", raising=False)
        monkeypatch.delenv("SENTENCE_TRANSFORMERS_HOME", raising=False)
        result = embedding_cache_dir()
        assert result is not None
        assert result != "/tmp"
        assert "huggingface" in result

    def test_honors_xdg_cache_home(self, monkeypatch, tmp_path):
        monkeypatch.delenv("HF_HOME", raising=False)
        monkeypatch.delenv("SENTENCE_TRANSFORMERS_HOME", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        assert embedding_cache_dir() == str(tmp_path / "huggingface" / "hub")

    def test_hf_home_already_set_takes_precedence(self, monkeypatch, tmp_path):
        """An explicit cache_folder outranks HF_HOME inside sentence-
        transformers, so we must NOT pass one when the user already set
        HF_HOME — otherwise we'd silently override their choice."""
        monkeypatch.setenv("HF_HOME", str(tmp_path))
        monkeypatch.delenv("SENTENCE_TRANSFORMERS_HOME", raising=False)
        assert embedding_cache_dir() is None

    def test_sentence_transformers_home_already_set_takes_precedence(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("HF_HOME", raising=False)
        monkeypatch.setenv("SENTENCE_TRANSFORMERS_HOME", str(tmp_path))
        assert embedding_cache_dir() is None

    def test_load_passes_cache_folder_to_sentence_transformer(self, monkeypatch):
        monkeypatch.delenv("HF_HOME", raising=False)
        monkeypatch.delenv("SENTENCE_TRANSFORMERS_HOME", raising=False)
        engine = EmbeddingEngine()
        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_st.return_value = MagicMock(get_embedding_dimension=lambda: 384)
            engine._ensure_model()
        _, kwargs = mock_st.call_args
        assert kwargs.get("cache_folder") == embedding_cache_dir()
        assert kwargs["cache_folder"] is not None

    def test_load_passes_none_cache_folder_when_hf_home_set(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("HF_HOME", str(tmp_path))
        monkeypatch.delenv("SENTENCE_TRANSFORMERS_HOME", raising=False)
        engine = EmbeddingEngine()
        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_st.return_value = MagicMock(get_embedding_dimension=lambda: 384)
            engine._ensure_model()
        _, kwargs = mock_st.call_args
        assert kwargs.get("cache_folder") is None


# ── Init ──────────────────────────────────────────────────────────────


class TestEmbeddingEngineInit:
    def test_default_dimensions(self):
        engine = EmbeddingEngine()
        assert engine.dimensions == 384

    def test_custom_dimensions(self):
        engine = EmbeddingEngine(dim=128)
        assert engine.dimensions == 128

    def test_default_device_is_cpu(self):
        engine = EmbeddingEngine()
        assert engine._device_requested == "cpu"

    def test_custom_device(self):
        engine = EmbeddingEngine(device="mps")
        assert engine._device_requested == "mps"

    def test_cache_is_ordered_dict(self):
        engine = EmbeddingEngine()
        assert isinstance(engine._cache, OrderedDict)


# ── Model revision pin (i7d3 reproducibility-gap fix, 2026-07-11) ──────


class TestModelRevisionPin:
    def test_default_pins_to_documented_revision(self):
        engine = EmbeddingEngine()
        assert engine.revision == DEFAULT_MODEL_REVISION

    def test_explicit_none_disables_pin(self):
        engine = EmbeddingEngine(revision=None)
        assert engine.revision is None

    def test_explicit_revision_overrides_default(self):
        engine = EmbeddingEngine(revision="deadbeef")
        assert engine.revision == "deadbeef"

    def test_load_passes_revision_to_sentence_transformer(self):
        engine = EmbeddingEngine(revision="pinned-sha")
        with patch("sentence_transformers.SentenceTransformer") as mock_st:
            mock_st.return_value = MagicMock(get_embedding_dimension=lambda: 384)
            engine._ensure_model()
        _, kwargs = mock_st.call_args
        assert kwargs.get("revision") == "pinned-sha"


# ── Fallback encoding ────────────────────────────────────────────────


class TestFallbackEncode:
    """Tests that work without sentence-transformers installed."""

    def test_encode_returns_bytes(self):
        engine = EmbeddingEngine(dim=64)
        engine._unavailable = True  # Force fallback
        result = engine.encode("test text")
        assert isinstance(result, bytes)
        assert len(result) == 64 * 4  # float32

    def test_encode_empty_returns_none(self):
        engine = EmbeddingEngine()
        assert engine.encode("") is None

    def test_deterministic(self):
        engine = EmbeddingEngine(dim=64)
        engine._unavailable = True
        a = engine.encode("hello world")
        b = engine.encode("hello world")
        assert a == b

    def test_different_texts_different_embeddings(self):
        engine = EmbeddingEngine(dim=64)
        engine._unavailable = True
        a = engine.encode("python programming")
        b = engine.encode("javascript framework")
        assert a != b

    def test_normalized(self):
        engine = EmbeddingEngine(dim=64)
        engine._unavailable = True
        result = engine.encode("test normalization")
        vec = np.frombuffer(result, dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        assert abs(norm - 1.0) < 1e-5


# ── Similarity ───────────────────────────────────────────────────────


class TestSimilarity:
    def test_identical_embeddings(self):
        engine = EmbeddingEngine(dim=64)
        engine._unavailable = True
        emb = engine.encode("same text")
        sim = engine.similarity(emb, emb)
        assert abs(sim - 1.0) < 1e-5

    def test_different_embeddings(self):
        engine = EmbeddingEngine(dim=64)
        engine._unavailable = True
        a = engine.encode("machine learning neural networks")
        b = engine.encode("cooking recipes italian food")
        sim = engine.similarity(a, b)
        assert sim < 1.0

    def test_mismatched_dimensions(self):
        engine = EmbeddingEngine()
        a = np.array([1.0, 0.0], dtype=np.float32).tobytes()
        b = np.array([1.0, 0.0, 0.0], dtype=np.float32).tobytes()
        assert engine.similarity(a, b) == 0.0


# ── LRU Cache ────────────────────────────────────────────────────────


class TestLRUCache:
    """LRU cache membership is now keyed by ``sha256(text)[:16]`` per
    ADR-0045 R5. Tests probe via ``_cache_key`` — never by raw text."""

    def test_cache_hit(self):
        engine = EmbeddingEngine(dim=32)
        engine._unavailable = True
        engine.encode("cached text")
        key = EmbeddingEngine._cache_key("cached text")
        assert key in engine._cache
        result = engine.encode("cached text")
        assert result == engine._cache[key]

    def test_lru_eviction_removes_oldest(self):
        engine = EmbeddingEngine(dim=16)
        engine._unavailable = True
        engine._cache_max = 3
        engine.encode("text 0")
        engine.encode("text 1")
        engine.encode("text 2")
        # Cache full: [text 0, text 1, text 2]
        engine.encode("text 3")
        # LRU eviction: text 0 evicted, [text 1, text 2, text 3]
        k = EmbeddingEngine._cache_key
        assert k("text 0") not in engine._cache
        assert k("text 1") in engine._cache
        assert k("text 2") in engine._cache
        assert k("text 3") in engine._cache
        assert len(engine._cache) == 3

    def test_lru_refresh_on_access(self):
        engine = EmbeddingEngine(dim=16)
        engine._unavailable = True
        engine._cache_max = 3
        engine.encode("text 0")
        engine.encode("text 1")
        engine.encode("text 2")
        # Access text 0 to refresh it (move to end)
        engine.encode("text 0")
        # Now add text 3 — text 1 should be evicted (oldest), not text 0
        engine.encode("text 3")
        k = EmbeddingEngine._cache_key
        assert k("text 0") in engine._cache  # refreshed, survives
        assert k("text 1") not in engine._cache  # oldest, evicted
        assert k("text 2") in engine._cache
        assert k("text 3") in engine._cache

    def test_no_full_flush(self):
        """Verify cache doesn't clear all entries at once."""
        engine = EmbeddingEngine(dim=16)
        engine._unavailable = True
        engine._cache_max = 3
        engine.encode("a")
        engine.encode("b")
        engine.encode("c")
        engine.encode("d")
        # After adding 4th, should still have 3 entries (not 1)
        assert len(engine._cache) == 3


# ── Batch encode ─────────────────────────────────────────────────────


class TestBatchEncode:
    def test_batch_fallback(self):
        engine = EmbeddingEngine(dim=32)
        engine._unavailable = True
        results = engine.encode_batch(["hello", "world", ""])
        assert len(results) == 3
        assert results[0] is not None
        assert results[1] is not None
        assert results[2] is None


# ── Device detection ─────────────────────────────────────────────────


class TestDeviceDetection:
    def test_detect_cuda(self):
        with patch.dict("sys.modules", {"torch": MagicMock()}):
            import sys

            mock_torch = sys.modules["torch"]
            mock_torch.cuda.is_available.return_value = True
            assert EmbeddingEngine._detect_device() == "cuda"

    def test_detect_mps(self):
        with patch.dict("sys.modules", {"torch": MagicMock()}):
            import sys

            mock_torch = sys.modules["torch"]
            mock_torch.cuda.is_available.return_value = False
            mock_torch.backends.mps.is_available.return_value = True
            assert EmbeddingEngine._detect_device() == "mps"

    def test_detect_cpu_fallback(self):
        with patch.dict("sys.modules", {"torch": MagicMock()}):
            import sys

            mock_torch = sys.modules["torch"]
            mock_torch.cuda.is_available.return_value = False
            mock_torch.backends.mps.is_available.return_value = False
            assert EmbeddingEngine._detect_device() == "cpu"

    def test_detect_no_torch(self):
        """When torch is not installed, fall back to cpu."""
        with patch.dict("sys.modules", {"torch": None}):
            assert EmbeddingEngine._detect_device() == "cpu"


# ── Device resolution ────────────────────────────────────────────────


class TestDeviceResolution:
    def test_cpu_direct(self):
        engine = EmbeddingEngine(device="cpu")
        assert engine._resolve_device() == "cpu"

    def test_mps_direct(self):
        engine = EmbeddingEngine(device="mps")
        assert engine._resolve_device() == "mps"

    def test_cuda_direct(self):
        engine = EmbeddingEngine(device="cuda")
        assert engine._resolve_device() == "cuda"

    def test_auto_delegates_to_detect(self):
        engine = EmbeddingEngine(device="auto")
        with patch.object(EmbeddingEngine, "_detect_device", return_value="mps"):
            assert engine._resolve_device() == "mps"

    def test_unknown_device_falls_back_to_cpu(self):
        engine = EmbeddingEngine(device="tpu")
        assert engine._resolve_device() == "cpu"

    def test_detect_once(self):
        """_resolve_device() caches; second call doesn't re-detect."""
        engine = EmbeddingEngine(device="auto")
        with patch.object(
            EmbeddingEngine, "_detect_device", return_value="mps"
        ) as mock:
            engine._resolve_device()
            engine._resolve_device()
            mock.assert_called_once()


# ── GPU fallback ─────────────────────────────────────────────────────


class TestGPUFallback:
    def test_runtime_error_on_gpu_triggers_cpu_fallback(self):
        engine = EmbeddingEngine(dim=32, device="mps")
        engine._unavailable = False
        mock_model = MagicMock()
        # First call raises RuntimeError (GPU failure), second succeeds (after CPU reload)
        mock_model.encode.side_effect = [
            RuntimeError("MPS backend error"),
            np.random.randn(32).astype(np.float32),
        ]
        mock_model.get_sentence_embedding_dimension.return_value = 32
        engine._model = mock_model

        # Patch _ensure_model to simulate successful CPU reload
        def fake_ensure():
            engine._model = mock_model

        engine._ensure_model = fake_ensure
        result = engine.encode("test")
        assert result is not None
        assert engine._device == "cpu"

    def test_runtime_error_on_cpu_reraises(self):
        engine = EmbeddingEngine(dim=32, device="cpu")
        engine._device = "cpu"
        engine._unavailable = False
        mock_model = MagicMock()
        mock_model.encode.side_effect = RuntimeError("genuine bug")
        engine._model = mock_model

        with pytest.raises(RuntimeError, match="genuine bug"):
            engine._encode_vec("test")

    def test_double_failure_falls_back_to_hash(self):
        engine = EmbeddingEngine(dim=32, device="cuda")
        engine._unavailable = False
        mock_model = MagicMock()
        mock_model.encode.side_effect = RuntimeError("GPU OOM")
        engine._model = mock_model

        # _fallback_to_cpu will fail to load → _unavailable = True
        def fake_ensure():
            engine._unavailable = True
            engine._model = None

        engine._ensure_model = fake_ensure
        result = engine.encode("test")
        # Should get hash fallback, not crash
        assert result is not None
        assert len(result) == 32 * 4

    def test_cpu_retry_failure_degrades_to_hash(self):
        engine = EmbeddingEngine(dim=32, device="mps")
        engine._unavailable = False
        mock_model = MagicMock()
        # Both GPU and CPU retry fail on this input
        mock_model.encode.side_effect = RuntimeError("bad input")
        mock_model.get_sentence_embedding_dimension.return_value = 32
        engine._model = mock_model

        def fake_ensure():
            engine._model = mock_model  # model loads fine, input is bad

        engine._ensure_model = fake_ensure
        result = engine.encode("test")
        assert result is not None  # hash fallback, not crash


# ── Singleton ────────────────────────────────────────────────────────


class TestSingleton:
    def setup_method(self):
        reset_embedding_engine()

    def teardown_method(self):
        reset_embedding_engine()

    def test_returns_same_instance(self):
        a = get_embedding_engine()
        b = get_embedding_engine()
        assert a is b

    def test_reset_clears_singleton(self):
        a = get_embedding_engine()
        reset_embedding_engine()
        b = get_embedding_engine()
        assert a is not b


# ── Env var override ─────────────────────────────────────────────────


class TestEnvVarOverride:
    def test_embedding_device_from_env(self, monkeypatch):
        monkeypatch.setenv("CORTEX_MEMORY_EMBEDDING_DEVICE", "mps")
        from mcp_server.infrastructure.memory_config import MemorySettings

        s = MemorySettings()
        assert s.EMBEDDING_DEVICE == "mps"

    def test_default_is_cpu(self):
        from mcp_server.infrastructure.memory_config import MemorySettings

        s = MemorySettings()
        assert s.EMBEDDING_DEVICE == "cpu"
