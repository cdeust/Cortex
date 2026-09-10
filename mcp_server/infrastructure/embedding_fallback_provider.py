"""source: ADR-0522"""

from __future__ import annotations

import numpy as np

from mcp_server.infrastructure.embedding_provider import _EmbeddingMathMixin
from mcp_server.shared.algorithmic_embedding import embed_text


class AlgorithmicEmbeddingProvider(_EmbeddingMathMixin):
    """Deterministic, download-free ``EmbeddingProvider`` implementation.

    source: ADR-0522"""

    def __init__(self, dim: int) -> None:
        self._dim = dim

    @property
    def dimensions(self) -> int:
        return self._dim

    @property
    def available(self) -> bool:
        """Always False: this provider is the fallback, backed by no neural model."""
        return False

    def encode(self, text: str) -> bytes | None:
        """Encode one text to a deterministic, L2-normalized float32 blob.

        precondition: none (``text`` may be empty).
        postcondition: ``None`` for empty text; otherwise a ``self._dim``-length
        float32 blob, deterministic in ``(text, dim)``.
        """
        if not text:
            return None
        vec = embed_text(text, self._dim)
        return vec.astype(np.float32).tobytes()

    def encode_batch(self, texts: list[str]) -> list[bytes | None]:
        """Encode a batch, preserving order and ``None`` for empty items."""
        return [self.encode(t) for t in texts]
