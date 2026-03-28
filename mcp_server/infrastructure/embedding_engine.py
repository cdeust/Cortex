"""Embedding engine for Cortex memory system.

Provides text → vector encoding for semantic similarity search.

Strategy (in priority order):
  1. sentence-transformers (if installed) — best quality, 384D
  2. Fallback: TF-IDF-like sparse-to-dense via Cortex's own text utilities

The engine is lazy-loading: no model initialization until first encode() call.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingEngine:
    """Lazy-loading embedding engine with graceful fallback."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", dim: int = 384) -> None:
        self._model_name = model_name
        self._dim = dim
        self._model: Any = None
        self._unavailable = False
        self._cache: dict[str, bytes] = {}
        self._cache_max = 128

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dim

    @property
    def available(self) -> bool:
        """Check if a real embedding model is available (without loading it)."""
        if self._model is not None:
            return True
        if self._unavailable:
            return False
        try:
            import sentence_transformers  # noqa: F401

            return True
        except ImportError:
            return False

    def _ensure_model(self) -> None:
        if self._model is not None or self._unavailable:
            return
        try:
            import os

            # Set offline mode BEFORE importing sentence_transformers to prevent
            # unauthenticated HF Hub requests. The import itself initializes
            # huggingface_hub which checks this env var at module load time.
            had_offline = os.environ.get("HF_HUB_OFFLINE")
            os.environ["HF_HUB_OFFLINE"] = "1"
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(
                    self._model_name, trust_remote_code=True, device="cpu"
                )
            except OSError:
                # Model not in local cache — need to download it once
                if had_offline is None:
                    del os.environ["HF_HUB_OFFLINE"]
                else:
                    os.environ["HF_HUB_OFFLINE"] = had_offline
                logger.info("Downloading embedding model: %s", self._model_name)
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(
                    self._model_name, trust_remote_code=True, device="cpu"
                )
            finally:
                if had_offline is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = had_offline

            actual_dim = self._model.get_sentence_embedding_dimension()
            if actual_dim != self._dim:
                self._dim = actual_dim
            logger.info("Loaded embedding model: %s (%dD)", self._model_name, self._dim)
        except ImportError:
            logger.warning(
                "sentence-transformers not installed; using hash-based fallback embeddings"
            )
            self._unavailable = True

    def encode(self, text: str) -> bytes | None:
        """Encode text to a float32 byte blob."""
        if not text:
            return None

        if text in self._cache:
            return self._cache[text]

        self._ensure_model()

        if self._unavailable:
            result = self._fallback_encode(text)
        else:
            vec = self._model.encode(text)
            arr = np.asarray(vec, dtype=np.float32)
            arr = self._normalize(arr)
            result = arr.tobytes()

        if len(self._cache) >= self._cache_max:
            self._cache.clear()
        self._cache[text] = result
        return result

    def encode_batch(self, texts: list[str]) -> list[bytes | None]:
        """Batch encode for efficiency."""
        self._ensure_model()
        if self._unavailable:
            return [self._fallback_encode(t) if t else None for t in texts]

        results = []
        vecs = self._model.encode(texts)
        for v in vecs:
            arr = self._normalize(np.asarray(v, dtype=np.float32))
            results.append(arr.tobytes())
        return results

    def similarity(self, embedding_a: bytes, embedding_b: bytes) -> float:
        """Cosine similarity between two embedding blobs."""
        a = np.frombuffer(embedding_a, dtype=np.float32)
        b = np.frombuffer(embedding_b, dtype=np.float32)
        if len(a) != len(b):
            return 0.0
        dot = float(np.dot(a, b))
        norm = float(np.linalg.norm(a) * np.linalg.norm(b))
        if norm == 0:
            return 0.0
        return dot / norm

    @staticmethod
    def to_list(embedding: bytes) -> list[float]:
        """Convert embedding blob to Python float list."""
        arr = np.frombuffer(embedding, dtype=np.float32)
        return arr.tolist()

    @staticmethod
    def from_list(values: list[float]) -> bytes:
        """Convert float list to embedding blob."""
        arr = np.asarray(values, dtype=np.float32)
        return arr.tobytes()

    @staticmethod
    def _normalize(arr: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr

    def _fallback_encode(self, text: str) -> bytes:
        """Hash-based deterministic embedding fallback.

        Uses character n-gram hashing to produce a fixed-dimension vector.
        Quality is much lower than learned embeddings but provides basic
        similarity ordering without any ML model.
        """
        vec = np.zeros(self._dim, dtype=np.float32)
        text_lower = text.lower()

        # Character trigram hashing
        for i in range(len(text_lower) - 2):
            trigram = text_lower[i : i + 3]
            h = int(hashlib.md5(trigram.encode()).hexdigest(), 16)
            idx = h % self._dim
            vec[idx] += 1.0

        # Word-level hashing for semantic signal
        words = text_lower.split()
        for word in words:
            if len(word) > 2:
                h = int(hashlib.md5(word.encode()).hexdigest(), 16)
                idx = h % self._dim
                vec[idx] += 2.0  # Words weighted more than trigrams

        vec = self._normalize(vec)
        return vec.astype(np.float32).tobytes()
