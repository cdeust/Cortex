"""Tests for mcp_server.infrastructure.embedding_engine — text embedding."""

import numpy as np

from mcp_server.infrastructure.embedding_engine import EmbeddingEngine


class TestEmbeddingEngineInit:
    def test_default_dimensions(self):
        engine = EmbeddingEngine()
        assert engine.dimensions == 384

    def test_custom_dimensions(self):
        engine = EmbeddingEngine(dim=128)
        assert engine.dimensions == 128


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


class TestCache:
    def test_cache_hit(self):
        engine = EmbeddingEngine(dim=32)
        engine._unavailable = True
        engine.encode("cached text")
        assert "cached text" in engine._cache
        # Second call should hit cache
        result = engine.encode("cached text")
        assert result == engine._cache["cached text"]

    def test_cache_eviction(self):
        engine = EmbeddingEngine(dim=16)
        engine._unavailable = True
        engine._cache_max = 3
        for i in range(5):
            engine.encode(f"text {i}")
        # Cache should have been cleared and only has latest entries
        assert len(engine._cache) <= 3


class TestBatchEncode:
    def test_batch_fallback(self):
        engine = EmbeddingEngine(dim=32)
        engine._unavailable = True
        results = engine.encode_batch(["hello", "world", ""])
        assert len(results) == 3
        assert results[0] is not None
        assert results[1] is not None
        assert results[2] is None
