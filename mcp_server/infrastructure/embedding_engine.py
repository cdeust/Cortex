"""Embedding engine for Cortex memory system.

Provides text -> vector encoding for semantic similarity search.

The engine is lazy-loading: no model initialization until first encode() call.

Device selection:
  Default is "cpu" for embedding consistency (GPU float32 arithmetic produces
  bit-different vectors from CPU). GPU is opt-in via CORTEX_MEMORY_EMBEDDING_DEVICE
  env var. Failed GPU inference retries on CPU (e.g. after OOM or MPS reset)
  before using the algorithmic fallback provider.

source: ADR-0520"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

import numpy as np

from mcp_server.infrastructure.embedding_cache import _EmbeddingCacheMixin
from mcp_server.infrastructure.embedding_factory import (
    current_embedding_mode,
    get_embedding_engine,
    reset_embedding_engine,
    use_fallback,
)
from mcp_server.infrastructure.embedding_fallback_provider import (
    AlgorithmicEmbeddingProvider,
)
from mcp_server.infrastructure.embedding_model_lifecycle import (
    DEFAULT_MODEL_REVISION,
    ModelState,
    _EmbeddingLifecycleMixin,
    embedding_cache_dir,
)
from mcp_server.infrastructure.embedding_provider import (
    EmbeddingProvider,
    _EmbeddingMathMixin,
)

logger = logging.getLogger(__name__)

# source: ADR-0520
__all__ = [
    "DEFAULT_MODEL_REVISION",
    "EmbeddingEngine",
    "EmbeddingProvider",
    "ModelState",
    "current_embedding_mode",
    "embedding_cache_dir",
    "get_embedding_engine",
    "reset_embedding_engine",
]


class EmbeddingEngine(
    _EmbeddingLifecycleMixin, _EmbeddingMathMixin, _EmbeddingCacheMixin
):
    """Lazy-loading neural embedding provider with graceful fallback.

        Implements ``EmbeddingProvider`` (embedding_provider.py). Composes the model
        lifecycle (``_EmbeddingLifecycleMixin``) and shared vector math
        (``_EmbeddingMathMixin``); this class owns the encode path and the LRU cache.

    source: ADR-0520"""

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        dim: int = 384,
        device: str = "cpu",
        revision: str | None = DEFAULT_MODEL_REVISION,
    ) -> None:
        self._model_name = model_name
        self._dim = dim
        self._device_requested = device
        self._device: str | None = None  # resolved once, cached
        # source: ADR-0520
        self._revision = revision
        self._model: Any = None
        self._unavailable = False
        self._model_state: ModelState = ModelState.UNINITIALIZED
        # source: ADR-0520
        self._fallback_provider = AlgorithmicEmbeddingProvider(dim)
        # source: ADR-0520
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        # source: ADR-0520
        self._cache_max = 128
        self._cache_hits = self._cache_misses = self._batch_reuses = 0

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def revision(self) -> str | None:
        """The pinned HF revision this engine loads (None = unpinned refs/main)."""
        return self._revision

    @property
    def dimensions(self) -> int:
        return self._dim

    @property
    def model_state(self) -> ModelState:
        """The current lifecycle state of the neural model load.

        source: ADR-0520"""
        return self._model_state

    @property
    def mode(self) -> str:
        """precondition: none.
                postcondition: forces model resolution if it has not been attempted,
                then returns ``"neural"`` when a sentence-transformers model is loaded,
                else ``"fallback"`` (algorithmic, download-free). Read by the store to
                tag each stored vector's space and by telemetry.

        source: ADR-0520"""
        if self._model_state is ModelState.UNINITIALIZED and not self._unavailable:
            self._ensure_model()
        return "fallback" if self._serve_fallback() else "neural"

    def _serve_fallback(self) -> bool:
        """Whether to route encode() to the algorithmic fallback provider.

        source: ADR-0520"""
        if self._model is not None:
            return False
        return use_fallback(self._model_state)

    @property
    def available(self) -> bool:
        """Check if a real embedding model is available (without loading it)."""
        if self._model is not None:
            return True
        if self._unavailable:
            return False
        try:
            import sentence_transformers  # noqa: PLC0415, F401 — optional-feature probe: ImportError here is a handled degraded mode

            return True
        except ImportError:
            return False

    # ── Encoding ──────────────────────────────────────────────────────

    def _encode_vec(self, text: str) -> bytes:
        """Encode text via model with GPU fallback. Always returns bytes."""
        model_input = self._prefix_guard.shorten(text) if self._prefix_guard else text
        try:
            vec = self._model.encode(model_input)
        except RuntimeError:
            if self._device == "cpu":
                raise  # source: ADR-0520
            self._fallback_to_cpu()
            if self._unavailable or self._model is None:
                return self._fallback_encode(text)
            try:
                vec = self._model.encode(model_input)
            except RuntimeError:
                logger.error("CPU encode also failed, using hash fallback")
                return self._fallback_encode(text)
        arr = np.asarray(vec, dtype=np.float32)
        arr = self._normalize(arr)
        return arr.tobytes()

    def encode(self, text: str) -> bytes | None:
        """Encode text to a float32 byte blob.

        source: ADR-0520"""
        if not text:
            return None

        key = self._cache_key(text)
        if key in self._cache:
            self._cache_hits += 1
            self._cache.move_to_end(key)
            return self._cache[key]
        self._cache_misses += 1

        self._ensure_model()

        # source: ADR-0520
        if self._serve_fallback():
            result = self._fallback_encode(text)
        else:
            result = self._encode_vec(text)

        self._cache_store(key, result)
        return result

    def encode_batch(self, texts: list[str]) -> list[bytes | None]:
        """Preserve the batch context; scalar-cache substitution changes vectors."""
        self._ensure_model()
        if self._serve_fallback():
            return self._fallback_provider.encode_batch(texts)

        try:
            vecs = self._model.encode(texts)
        except RuntimeError:
            if self._device == "cpu":
                raise
            self._fallback_to_cpu()
            if self._unavailable or self._model is None:
                return [self._fallback_encode(t) if t else None for t in texts]
            try:
                vecs = self._model.encode(texts)
            except RuntimeError:
                logger.error("CPU batch encode also failed, using hash fallback")
                return [self._fallback_encode(t) if t else None for t in texts]

        results = []
        for v in vecs:
            arr = self._normalize(np.asarray(v, dtype=np.float32))
            results.append(arr.tobytes())
        return results

    def warm_cache(self, texts: list[str]) -> None:
        """Pre-populate the LRU cache for ``texts`` via one ``encode_batch()`` call.

                LRU eviction (``_cache_max``) still applies -- if ``texts`` exceeds
                the cache size, the earliest-warmed entries may be evicted before
                their ``encode()`` call runs, which only forgoes the optimization
                for those; ``encode()`` still returns a correct vector via its own
                per-text fallback path.

        source: ADR-0520"""
        to_encode = list(
            dict.fromkeys(
                t for t in texts if t and self._cache_key(t) not in self._cache
            )
        )
        if not to_encode:
            return
        vecs = self.encode_batch(to_encode)
        for text, vec in zip(to_encode, vecs, strict=True):
            if vec is not None:
                self._cache_store(self._cache_key(text), vec)

    def _fallback_encode(self, text: str) -> bytes:
        """precondition: ``text`` is a non-empty str (the GPU-failure and
                model-absent paths only reach here with real content).
                postcondition: returns a ``self._dim``-length, L2-normalized float32
                blob from ``AlgorithmicEmbeddingProvider`` — the SECOND provider.

        source: ADR-0520"""
        blob = self._fallback_provider.encode(text)
        # source: ADR-0520
        return blob if blob is not None else np.zeros(self._dim, np.float32).tobytes()
