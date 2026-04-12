"""Embedding engine for Cortex memory system.

Provides text -> vector encoding for semantic similarity search.

Strategy (in priority order):
  1. sentence-transformers (if installed) -- best quality, 384D
  2. Fallback: TF-IDF-like sparse-to-dense via Cortex's own text utilities

The engine is lazy-loading: no model initialization until first encode() call.

Device selection:
  Default is "cpu" for embedding consistency (GPU float32 arithmetic produces
  bit-different vectors from CPU). GPU is opt-in via CORTEX_MEMORY_EMBEDDING_DEVICE
  env var. Switching devices mid-deployment means new embeddings won't be
  bit-identical to existing ones -- cosine similarity degradation is small
  (~1e-7) but retrieval ranking can shift for borderline results.

  If GPU inference fails at runtime (OOM, MPS reset after sleep), the engine
  automatically falls back to CPU. If CPU also fails, it degrades to hash-based
  fallback encoding. The engine never crashes on encode().
"""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ── Process-wide singleton ────────────────────────────────────────────
# One EmbeddingEngine per process. Handlers call get_embedding_engine()
# instead of creating their own instances. This guarantees: one model,
# one device, no mixed-device embeddings, ~5x memory savings.
_singleton: EmbeddingEngine | None = None


def get_embedding_engine() -> "EmbeddingEngine":
    """Return the process-wide EmbeddingEngine singleton."""
    global _singleton
    if _singleton is None:
        from mcp_server.infrastructure.memory_config import get_memory_settings

        s = get_memory_settings()
        _singleton = EmbeddingEngine(dim=s.EMBEDDING_DIM, device=s.EMBEDDING_DEVICE)
    return _singleton


def reset_embedding_engine() -> None:
    """Clear singleton (for testing only)."""
    global _singleton
    _singleton = None


class EmbeddingEngine:
    """Lazy-loading embedding engine with graceful fallback."""

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        dim: int = 384,
        device: str = "cpu",
    ) -> None:
        self._model_name = model_name
        self._dim = dim
        self._device_requested = device
        self._device: str | None = None  # resolved once, cached
        self._model: Any = None
        self._unavailable = False
        self._cache: OrderedDict[str, bytes] = OrderedDict()
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

    # ── Device detection ──────────────────────────────────────────────

    @staticmethod
    def _detect_device() -> str:
        """Probe hardware: CUDA > MPS > CPU."""
        try:
            import torch

            if torch.cuda.is_available():
                logger.info("GPU auto-detect: CUDA available")
                return "cuda"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                logger.info("GPU auto-detect: MPS available")
                return "mps"
        except ImportError:
            logger.debug("GPU auto-detect: torch not available, using cpu")
        return "cpu"

    def _resolve_device(self) -> str:
        """Resolve and cache the target device. Called once per instance."""
        if self._device is not None:
            return self._device
        requested = self._device_requested
        if requested == "auto":
            self._device = self._detect_device()
        elif requested in ("cpu", "cuda", "mps"):
            self._device = requested
        else:
            logger.warning("Unknown embedding device %r, using cpu", requested)
            self._device = "cpu"
        logger.info(
            "Embedding device: %s (requested: %s)", self._device, requested,
        )
        return self._device

    def _fallback_to_cpu(self) -> None:
        """Reload model on CPU after GPU failure."""
        logger.warning(
            "GPU inference failed (device=%s) — reloading on CPU", self._device,
        )
        self._device = "cpu"
        self._model = None
        self._ensure_model()

    # ── Model loading ─────────────────────────────────────────────────

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
            device = self._resolve_device()
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self._model_name, device=device)
            except OSError:
                # Model not in local cache — need to download it once
                if had_offline is None:
                    del os.environ["HF_HUB_OFFLINE"]
                else:
                    os.environ["HF_HUB_OFFLINE"] = had_offline
                logger.info("Downloading embedding model: %s", self._model_name)
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self._model_name, device=device)
            finally:
                if had_offline is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = had_offline

            actual_dim = self._model.get_sentence_embedding_dimension()
            if actual_dim != self._dim:
                self._dim = actual_dim
            logger.info(
                "Loaded embedding model: %s (%dD, device=%s)",
                self._model_name,
                self._dim,
                device,
            )
        except ImportError:
            logger.warning(
                "sentence-transformers not installed; using hash-based fallback embeddings. "
                "Installing in background for next session..."
            )
            self._unavailable = True
            self._trigger_background_install()

    def _trigger_background_install(self) -> None:
        """Install sentence-transformers in the background.

        Runs pip install as a detached subprocess so it doesn't block
        the current session. Next session will have real embeddings.
        """
        import os
        import subprocess
        import sys

        target = os.environ.get("CLAUDE_PLUGIN_DATA", "")
        if target:
            target = os.path.join(target, "deps")

        cmd = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-q",
            "sentence-transformers>=2.2.0,<4.0.0",
        ]
        if target:
            cmd.extend(["--target", target])

        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.info("Background install of sentence-transformers started")
        except Exception as exc:
            logger.debug("Background install failed to start: %s", exc)

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
                logger.error("CPU encode also failed, using hash fallback")
                return self._fallback_encode(text)
        arr = np.asarray(vec, dtype=np.float32)
        arr = self._normalize(arr)
        return arr.tobytes()

    def encode(self, text: str) -> bytes | None:
        """Encode text to a float32 byte blob."""
        if not text:
            return None

        if text in self._cache:
            self._cache.move_to_end(text)
            return self._cache[text]

        self._ensure_model()

        if self._unavailable:
            result = self._fallback_encode(text)
        else:
            result = self._encode_vec(text)

        if len(self._cache) >= self._cache_max:
            self._cache.popitem(last=False)  # evict LRU entry
        self._cache[text] = result
        return result

    def encode_batch(self, texts: list[str]) -> list[bytes | None]:
        """Batch encode for efficiency."""
        self._ensure_model()
        if self._unavailable:
            return [self._fallback_encode(t) if t else None for t in texts]

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
            h = int(
                hashlib.sha256(trigram.encode()).hexdigest(), 16
            )  # non-security: deterministic bucketing
            idx = h % self._dim
            vec[idx] += 1.0

        # Word-level hashing for semantic signal
        words = text_lower.split()
        for word in words:
            if len(word) > 2:
                h = int(
                    hashlib.sha256(word.encode()).hexdigest(), 16
                )  # non-security: deterministic bucketing
                idx = h % self._dim
                vec[idx] += 2.0  # Words weighted more than trigrams

        vec = self._normalize(vec)
        return vec.astype(np.float32).tobytes()
