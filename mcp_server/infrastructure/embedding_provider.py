"""This module defines the interface the rest of the system consumes to turn text
into vectors, decoupled from *which* encoder produces them:

source: ADR-0525"""

from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Any implementation returns L2-normalized ``float32`` blobs of ``dimensions``
        length (or ``None`` for empty text). ``EmbeddingEngine`` is the neural
        implementation; the seam lets a second encoder be substituted without
        touching a single caller.

    source: ADR-0525"""

    @property
    def dimensions(self) -> int:
        """Vector dimension of the blobs this provider emits."""
        ...

    @property
    def available(self) -> bool:
        """Whether a real (neural) model backs this provider right now."""
        ...

    def encode(self, text: str) -> bytes | None:
        """Encode one text to a float32 blob (``None`` for empty input)."""
        ...

    def encode_batch(self, texts: list[str]) -> list[bytes | None]:
        """Encode a batch, preserving order and ``None`` for empty items."""
        ...

    def similarity(self, embedding_a: bytes, embedding_b: bytes) -> float:
        """Cosine similarity between two blobs from this provider."""
        ...


class _EmbeddingMathMixin:
    """Stateless vector arithmetic shared by every embedding provider.

    source: ADR-0525"""

    @staticmethod
    def _cache_key(text: str) -> str:
        """Return the SHA256[:16] cache key for ``text``.

                precondition: ``text`` is a non-empty str.
                postcondition: returns a 16-char lowercase hex string; the same
                input always produces the same key; key length is independent of
                ``len(text)``.

        source: ADR-0525"""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _normalize(arr: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr

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
