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

Model revision pin (reproducibility gap closed 2026-07-11, incident i7d3):
  ``huggingface_hub`` resolves an unpinned model name against the repo's
  moving ``refs/main`` pointer. Root-cause investigation of a benchmark
  regression found TWO snapshots cached locally for
  ``sentence-transformers/all-MiniLM-L6-v2`` (``c9745ed1...`` from
  2026-04-04 and ``1110a243...`` from 2026-06-09) — ``refs/main`` had moved
  between them. In that specific incident the underlying
  ``model.safetensors``/``config.json``/``tokenizer.json`` blobs were
  confirmed BYTE-IDENTICAL across both snapshots (same SHA256 content
  hash) by direct cache inspection, so it was not the cause of THAT
  regression — but the gap itself is real and unbounded: nothing stops a
  future upstream repo change (a genuine weight update, not just a
  metadata/README commit) from silently altering embeddings for every
  caller that resolves ``main`` at load time, with no signal in
  ``uv.lock`` (which pins the Python package, not the HF model weights).
  ``DEFAULT_MODEL_REVISION`` below pins the exact snapshot verified during
  that investigation; ``EmbeddingEngine`` uses it whenever the caller does
  not supply an explicit ``revision``. source: measured on 2026-07-11 via
  ``~/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/refs/main``
  and blob-hash comparison of the two cached snapshots.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections import OrderedDict
from typing import Any

import numpy as np

from mcp_server.shared.platform import cache_dir as _base_cache_dir

# source: measured 2026-07-11 (incident i7d3) — see module docstring
# "Model revision pin" section for the full derivation and the blob-hash
# verification that this snapshot's weights are byte-identical to the
# immediately-prior cached snapshot.
DEFAULT_MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"

logger = logging.getLogger(__name__)


class _FallbackRequired(Exception):
    """Internal signal: no neural model is loadable, engage the fallback.

    Raised inside ``_ensure_model`` (zero-download requested, or a download
    failed) and caught in the same method to route to ``_engage_fallback``.
    Never escapes the module.
    """


def _zero_download() -> bool:
    """Whether the operator opted out of any model download (issue #169).

    source: opt-in env contract — ``CORTEX_EMBEDDING_ZERO_DOWNLOAD`` in
    {``1``, ``true``} forces the algorithmic fallback when the model is not
    already cached, so a sandboxed / offline install never blocks on a fetch.
    """
    return os.environ.get("CORTEX_EMBEDDING_ZERO_DOWNLOAD", "").lower() in ("1", "true")


def embedding_cache_dir() -> str | None:
    """Resolve the ``cache_folder`` to pass to ``SentenceTransformer``.

    Mirrors ``mcp_server.core.reranker.reranker_cache_dir`` (hardened
    after the FlashRank /tmp incident, commit bb1c581f): same shared,
    XDG-aware ``mcp_server.shared.platform.cache_dir()`` base, laid out
    under ``huggingface/hub`` to match the directory
    ``sentence-transformers``/``huggingface_hub`` already write
    ``models--org--name`` snapshots into by default (``$HF_HOME/hub``).

    Precedence, decided for consistency with how ``huggingface_hub``
    itself resolves its cache (``cache_folder`` passed to
    ``SentenceTransformer`` takes priority over both env vars inside the
    library, so passing one unconditionally would silently override a
    choice the user already made): if ``HF_HOME`` or
    ``SENTENCE_TRANSFORMERS_HOME`` is set in the environment, return
    ``None`` and let the library resolve its own default from that env
    var. Otherwise return our durable, shared cache path so a caller who
    set neither var still gets a deterministic, XDG-aware location
    instead of depending entirely on ``huggingface_hub``'s built-in
    resolution (issue #124 — the reranker was hardened this way in
    bb1c581f; embeddings had no equivalent).
    """
    if os.environ.get("HF_HOME") or os.environ.get("SENTENCE_TRANSFORMERS_HOME"):
        return None
    return str(_base_cache_dir() / "huggingface" / "hub")


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


def current_embedding_mode() -> str:
    """Return the process-wide embedding provenance without a mandatory encode.

    precondition: none.
    postcondition: ``"neural"`` or ``"fallback"`` if the singleton exists and
    has resolved (or can resolve) its model; ``"unknown"`` if no engine has been
    constructed yet. Read by ``get_telemetry`` (to surface fallback mode) and by
    the SQLite store (to stamp each vector's space so incompatible spaces never
    cross-rank). Does not construct an engine as a side effect.
    """
    if _singleton is None:
        return "unknown"
    return _singleton.mode


class EmbeddingEngine:
    """Lazy-loading embedding engine with graceful fallback.

    Cache key discipline (ADR-0045 R5): the LRU cache is keyed by
    ``sha256(text)[:16]`` (16 hex chars = 8 bytes of entropy), never by
    raw text. A 100 KB user memory yields a 16-byte key instead of
    100 KB of key bytes — at ``_cache_max = 128`` this bounds cache key
    memory to ~2 KB regardless of input size. A 16-char SHA256 prefix
    has 2^64 possible values; the birthday-bound collision probability
    at 128 cached entries is ~4.6e-16 (negligible). See
    ``_cache_key`` for the single point of truth.
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
        # against. See module docstring "Model revision pin".
        self._revision = revision
        self._model: Any = None
        self._unavailable = False
        # Embedding provenance, resolved once model loading is attempted:
        #   None      → not yet attempted (no encode() has run)
        #   "neural"  → sentence-transformers model loaded; learned vectors
        #   "fallback"→ algorithmic (download-free) vectors, see issue #169
        # Exposed via ``mode`` and the module-level ``current_embedding_mode``
        # so telemetry and the store can keep the two incompatible vector
        # spaces from silently cross-ranking.
        self._mode: str | None = None
        # Cache keyed by sha256(text)[:16] — see class docstring / ADR-0045 R5.
        self._cache: OrderedDict[str, bytes] = OrderedDict()
        self._cache_max = 128

    # ── Cache key (ADR-0045 R5) ───────────────────────────────────────

    @staticmethod
    def _cache_key(text: str) -> str:
        """Return the SHA256[:16] cache key for ``text``.

        precondition: ``text`` is a non-empty str.
        postcondition: returns a 16-char lowercase hex string; the same
        input always produces the same key; key length is independent of
        ``len(text)``.

        Source: ADR-0045 R5 — ``hashlib.sha256(text.encode()).hexdigest()[:16]``
        is the mandated cache-key form for any memoization layer over
        user-provided strings.
        """
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

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
    def mode(self) -> str:
        """Embedding provenance: ``"neural"`` or ``"fallback"``.

        precondition: none.
        postcondition: forces model resolution if it has not happened yet, then
        returns ``"neural"`` when a sentence-transformers model is loaded, else
        ``"fallback"`` (algorithmic, download-free — issue #169). Stable for the
        life of the instance once resolved, except that a ``"fallback"``
        instance is never silently promoted: a new session that finds the model
        present resolves to ``"neural"`` from the start.
        """
        if self._mode is None:
            self._ensure_model()
        return self._mode or "fallback"

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
            "Embedding device: %s (requested: %s)",
            self._device,
            requested,
        )
        return self._device

    def _fallback_to_cpu(self) -> None:
        """Reload model on CPU after GPU failure."""
        logger.warning(
            "GPU inference failed (device=%s) — reloading on CPU",
            self._device,
        )
        self._device = "cpu"
        self._model = None
        self._ensure_model()

    # ── Model loading ─────────────────────────────────────────────────

    def _ensure_model(self) -> None:
        if self._model is not None or self._unavailable:
            return
        try:
            # Collect cache-miss exception types: OSError covers transformers'
            # config loader; LocalEntryNotFoundError covers huggingface_hub
            # (>=0.22) which raises a non-OSError on local-only cache miss.
            _cache_miss: tuple[type[Exception], ...] = (OSError,)
            try:
                from huggingface_hub.errors import LocalEntryNotFoundError

                _cache_miss = (OSError, LocalEntryNotFoundError)
            except ImportError:
                pass

            device = self._resolve_device()
            from sentence_transformers import SentenceTransformer

            # cache_folder: explicit, XDG-aware default (mirrors the
            # reranker's /tmp-incident hardening, bb1c581f) unless the
            # user already set HF_HOME / SENTENCE_TRANSFORMERS_HOME, in
            # which case we pass None and defer to their choice. See
            # embedding_cache_dir() docstring for the full precedence
            # rationale (issue #124).
            cache_folder = embedding_cache_dir()

            # local_files_only=True keeps the load hermetic (no HF Hub
            # requests) whenever the model is already cached. It must be
            # an explicit argument, not the HF_HUB_OFFLINE env var: hub
            # freezes that env var into module constants at first import,
            # so the previous unset-env-and-retry fallback still ran
            # offline, leaving the download path unreachable on a fresh
            # install (reproduced 2026-07-03, clean-env harness run).
            # source: kwarg added in sentence-transformers v3.0.0
            # (absent in v2.3.0 SentenceTransformer.py; pyproject floor
            # raised to match).
            try:
                self._model = SentenceTransformer(
                    self._model_name,
                    device=device,
                    local_files_only=True,
                    revision=self._revision,
                    cache_folder=cache_folder,
                )
            except _cache_miss as exc:
                # Model not in local cache (at all, or not at the pinned
                # revision). Two ways forward:
                #   * zero-download requested → engage the algorithmic
                #     fallback immediately, never touch the network (#169);
                #   * otherwise download once. First use on the zero-config
                #     install path lands here by design (the plugin
                #     postInstall skips the eager pre-cache). If the download
                #     itself fails (offline install), we still fall back
                #     LOUDLY instead of crashing. Size figure per PRIVACY.md
                #     "one-time model download".
                if _zero_download():
                    raise _FallbackRequired(
                        "CORTEX_EMBEDDING_ZERO_DOWNLOAD set and model not cached"
                    ) from exc
                logger.info(
                    "Downloading embedding model %s (revision=%s) — "
                    "~100 MB, one-time; cached under %s, then runs fully offline",
                    self._model_name,
                    self._revision or "refs/main",
                    cache_folder or "$HF_HOME",
                )
                try:
                    self._model = SentenceTransformer(
                        self._model_name,
                        device=device,
                        revision=self._revision,
                        cache_folder=cache_folder,
                    )
                except Exception as dl_exc:  # network/offline/hub errors
                    raise _FallbackRequired(
                        f"embedding model download failed: {dl_exc}"
                    ) from dl_exc

            # sentence-transformers 5.x renamed get_sentence_embedding_dimension
            # → get_embedding_dimension. Prefer the new name; fall back for <5.
            get_dim = getattr(
                self._model,
                "get_embedding_dimension",
                self._model.get_sentence_embedding_dimension,
            )
            actual_dim = get_dim()
            if actual_dim != self._dim:
                self._dim = actual_dim
            self._mode = "neural"
            logger.info(
                "Loaded embedding model: %s (%dD, device=%s)",
                self._model_name,
                self._dim,
                device,
            )
        except ImportError:
            self._engage_fallback("sentence-transformers not installed")
            self._trigger_background_install()
        except _FallbackRequired as exc:
            self._engage_fallback(str(exc))

    def _engage_fallback(self, reason: str) -> None:
        """Switch to the deterministic algorithmic embedder — LOUD (issue #169).

        precondition: called from ``_ensure_model`` when no neural model can be
        loaded.
        postcondition: ``_unavailable`` is True and ``mode`` is ``"fallback"``;
        exactly one WARNING is logged naming the reason, so the degrade is never
        silent (CLAUDE.md "no silent fallbacks"). The next session upgrades
        transparently once the model is present.
        """
        logger.warning(
            "Embedding fallback ENGAGED (%s): using deterministic algorithmic "
            "embeddings (issue #169) — download-free, lower fidelity than "
            "sentence-transformers, upgrades automatically when the model is "
            "present. Fallback vectors are tagged 'fallback' and are kept from "
            "cross-ranking against neural vectors.",
            reason,
        )
        self._unavailable = True
        self._mode = "fallback"

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

        if self._unavailable:
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
        """Deterministic, download-free algorithmic embedding (issue #169).

        precondition: ``text`` is a non-empty str.
        postcondition: returns a ``self._dim``-dimension float32 blob in the
        SAME dimension contract as the neural encoder (``dim`` from
        ``EmbeddingEngine`` construction, itself sourced from
        ``settings.EMBEDDING_DIM``), L2-normalized. The vector lives in a
        DIFFERENT geometry from the neural space — the store tags it
        ``"fallback"`` so the two never cross-rank. Delegates to the pure
        ``shared.algorithmic_embedding`` (TF + Random Indexing + co-occurrence
        bridging); see that module for the signal selection and sources.
        """
        from mcp_server.shared.algorithmic_embedding import embed_text

        vec = embed_text(text, self._dim)
        return vec.astype(np.float32).tobytes()
