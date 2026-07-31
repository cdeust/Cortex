"""Embedding engine for Cortex memory system.

Provides text -> vector encoding for semantic similarity search.

Strategy (selected by the factory per ``ModelState``, issue #169):
  1. sentence-transformers (``ModelState.LOADED``) -- best quality, 384D
  2. Download-free algorithmic fallback (every non-LOADED state) --
     ``embedding_fallback_provider.AlgorithmicEmbeddingProvider``, the SECOND
     ``EmbeddingProvider`` implementation. No state maps to nothing.

The engine is lazy-loading: no model initialization until first encode() call.

Structure (Cortex#173 — the file was split along three seams):
  * ``embedding_provider.EmbeddingProvider`` — the interface consumers depend
    on; ``EmbeddingEngine`` below is the neural implementation, the algorithmic
    fallback is the second.
  * ``embedding_model_lifecycle`` — device resolution + the explicit model-load
    state machine (``ModelState``: package absent / model files absent / load
    raised / loaded). See that module's docstring for the revision-pin history.
  * ``embedding_factory`` — the composition root: it wires the two providers and
    owns the state→provider selection (``use_fallback``, ``current_embedding_mode``).
  * this module — the concrete neural provider (encode path + LRU cache).

Device selection:
  Default is "cpu" for embedding consistency (GPU float32 arithmetic produces
  bit-different vectors from CPU). GPU is opt-in via CORTEX_MEMORY_EMBEDDING_DEVICE
  env var. If GPU inference fails at runtime (OOM, MPS reset after sleep), the
  engine automatically falls back to CPU; if CPU also fails, it degrades to the
  algorithmic fallback provider. The engine never crashes on encode().
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

import numpy as np

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

# Re-exported for backward compatibility: callers and tests import these names
# from ``embedding_engine`` directly (they lived here before the Cortex#173
# split). The definitions now live in the seam modules — ``embedding_provider``
# (interface), ``embedding_model_lifecycle`` (revision pin + cache dir), and
# ``embedding_factory`` (composition root / selection + telemetry mode).
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


class EmbeddingEngine(_EmbeddingLifecycleMixin, _EmbeddingMathMixin):
    """Lazy-loading neural embedding provider with graceful fallback.

    Implements ``EmbeddingProvider`` (embedding_provider.py). Composes the model
    lifecycle (``_EmbeddingLifecycleMixin``) and shared vector math
    (``_EmbeddingMathMixin``); this class owns the encode path and the LRU cache.

    Cache key discipline (ADR-0045 R5): the LRU cache is keyed by
    ``sha256(text)[:16]`` (16 hex chars = 8 bytes of entropy), never by
    raw text. A 100 KB user memory yields a 16-byte key instead of
    100 KB of key bytes — at ``_cache_max = 128`` this bounds cache key
    memory to ~2 KB regardless of input size. A 16-char SHA256 prefix
    has 2^64 possible values; the birthday-bound collision probability
    at 128 cached entries is ~4.6e-16 (negligible).
    """

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
        # revision=None means "resolve refs/main at load time" (the
        # pre-i7d3 unpinned behavior) — an explicit opt-out for callers
        # that pass a different model_name this pin was never verified
        # against. See embedding_model_lifecycle "Model revision pin".
        self._revision = revision
        self._model: Any = None
        self._unavailable = False
        self._model_state: ModelState = ModelState.UNINITIALIZED
        # The SECOND provider (issue #169): the download-free algorithmic
        # encoder the factory routes to for every non-LOADED ModelState. Same
        # dimension contract as this neural engine.
        self._fallback_provider = AlgorithmicEmbeddingProvider(dim)
        # Cache keyed by sha256(text)[:16] — see class docstring / ADR-0045 R5.
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._cache_max = 128

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
        """The current lifecycle state of the neural model load (Cortex#173)."""
        return self._model_state

    @property
    def mode(self) -> str:
        """Embedding provenance: ``"neural"`` or ``"fallback"`` (issue #169).

        precondition: none.
        postcondition: forces model resolution if it has not been attempted,
        then returns ``"neural"`` when a sentence-transformers model is loaded,
        else ``"fallback"`` (algorithmic, download-free). Read by the store to
        tag each stored vector's space and by telemetry.
        """
        if self._model_state is ModelState.UNINITIALIZED and not self._unavailable:
            self._ensure_model()
        return "fallback" if self._serve_fallback() else "neural"

    def _serve_fallback(self) -> bool:
        """Whether to route encode() to the algorithmic fallback provider.

        After ``_ensure_model``, a loaded neural model has ``self._model`` set
        (state LOADED); every fallback ModelState leaves ``self._model`` None.
        A present model always takes the neural path; otherwise the factory's
        per-ModelState mapping (``use_fallback``) decides — so no state maps to
        nothing (issue #169).
        """
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
        except ImportError:
            return False
        else:
            return True

    # ── Encoding ──────────────────────────────────────────────────────

    def _encode_vec(self, text: str) -> bytes:
        """Encode text via model with GPU fallback. Always returns bytes."""
        try:
            vec = self._model.encode(text)
        except RuntimeError:
            if self._device == "cpu":
                raise  # Already on CPU — genuine bug, don't mask
            self._fallback_to_cpu()
            if self._unavailable or self._model is None:
                return self._fallback_encode(text)
            try:
                vec = self._model.encode(text)
            except RuntimeError:
                logger.exception("CPU encode also failed, using hash fallback")
                return self._fallback_encode(text)
        arr = np.asarray(vec, dtype=np.float32)
        arr = self._normalize(arr)
        return arr.tobytes()

    def encode(self, text: str) -> bytes | None:
        """Encode text to a float32 byte blob.

        The LRU cache is keyed by ``sha256(text)[:16]`` per ADR-0045 R5
        — never by raw text — so a 100 KB memory contributes 16 bytes of
        key storage, not 100 KB.
        """
        if not text:
            return None

        key = self._cache_key(text)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]

        self._ensure_model()

        # Selection per ModelState is owned by the factory (issue #169):
        # LOADED → neural encode; every other state → the algorithmic fallback.
        if self._serve_fallback():
            result = self._fallback_encode(text)
        else:
            result = self._encode_vec(text)

        if len(self._cache) >= self._cache_max:
            self._cache.popitem(last=False)  # evict LRU entry
        self._cache[key] = result
        return result

    def encode_batch(self, texts: list[str]) -> list[bytes | None]:
        """Batch encode for efficiency."""
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
                logger.exception("CPU batch encode also failed, using hash fallback")
                return [self._fallback_encode(t) if t else None for t in texts]

        results = []
        for v in vecs:
            arr = self._normalize(np.asarray(v, dtype=np.float32))
            results.append(arr.tobytes())
        return results

    def _fallback_encode(self, text: str) -> bytes:
        """Delegate to the algorithmic fallback provider (issue #169).

        precondition: ``text`` is a non-empty str (the GPU-failure and
        model-absent paths only reach here with real content).
        postcondition: returns a ``self._dim``-length, L2-normalized float32
        blob from ``AlgorithmicEmbeddingProvider`` — the SECOND provider.
        """
        blob = self._fallback_provider.encode(text)
        # Non-empty text always yields a vector; guard the type only.
        return blob if blob is not None else np.zeros(self._dim, np.float32).tobytes()
