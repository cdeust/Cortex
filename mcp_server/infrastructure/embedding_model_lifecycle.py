"""Model lifecycle for the embedding engine — device + load state machine.

Split out of ``embedding_engine.py`` (Cortex#173) so the download/cache/load
lifecycle is an explicit, testable seam rather than an inline tangle. The
``ModelState`` enum names the distinct outcomes the loader can reach — the
state space where a silent-degradation bug can hide:

  * ``UNINITIALIZED``       — no load attempted yet (lazy engine).
  * ``LOADED``              — a neural model is in hand.
  * ``PACKAGE_ABSENT``      — ``import sentence_transformers`` failed; the
                              package is not installed at all.
  * ``MODEL_FILES_ABSENT``  — the package is present but the weights are not in
                              the local cache; a one-time download is attempted.
  * ``LOAD_RAISED``         — construction raised (corrupt cache, or an offline
                              download attempt failed).

Behaviour is preserved verbatim from the pre-split ``_ensure_model``:
``PACKAGE_ABSENT`` degrades to the hash fallback + a background install;
``MODEL_FILES_ABSENT`` downloads; ``LOAD_RAISED`` propagates. The states are now
*named*, which is the seam a second (download-free) encoder plugs into later.

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

import enum
import logging
import os
from typing import Any

from mcp_server.infrastructure.embedding_downloads import (
    trigger_background_install,
    trigger_background_model_download,
)
from mcp_server.shared.platform import cache_dir as _base_cache_dir

# source: measured 2026-07-11 (incident i7d3) — see module docstring
# "Model revision pin" section for the full derivation and the blob-hash
# verification that this snapshot's weights are byte-identical to the
# immediately-prior cached snapshot.
DEFAULT_MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"

logger = logging.getLogger(__name__)


class ModelState(enum.Enum):
    """Explicit lifecycle states of the neural model load (Cortex#173)."""

    UNINITIALIZED = enum.auto()
    LOADED = enum.auto()
    PACKAGE_ABSENT = enum.auto()
    MODEL_FILES_ABSENT = enum.auto()
    LOAD_RAISED = enum.auto()


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


class _EmbeddingLifecycleMixin:
    """Device resolution + the neural-model load state machine.

    A mixin so ``EmbeddingEngine`` keeps exposing ``_detect_device`` /
    ``_resolve_device`` / ``_ensure_model`` on the class (the tests patch and
    call them there). Reads/writes the engine attributes declared below, all
    owned by ``EmbeddingEngine.__init__``.
    """

    _model: Any
    _model_name: str
    _dim: int
    _revision: str | None
    _device: str | None
    _device_requested: str
    _unavailable: bool
    _model_state: ModelState

    # ── Device detection ──────────────────────────────────────────────

    @staticmethod
    def _detect_device() -> str:
        """Probe hardware: CUDA > MPS > CPU."""
        try:
            import torch  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode

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
        logger.info("Embedding device: %s (requested: %s)", self._device, requested)
        return self._device

    def _fallback_to_cpu(self) -> None:
        """Reload model on CPU after GPU failure."""
        logger.warning(
            "GPU inference failed (device=%s) — reloading on CPU", self._device
        )
        self._device = "cpu"
        self._model = None
        self._ensure_model()

    # ── Model loading (state machine) ─────────────────────────────────

    @staticmethod
    def _cache_miss_types() -> tuple[type[Exception], ...]:
        """Exception types that mean 'weights not in local cache'.

        OSError covers transformers' config loader; ``LocalEntryNotFoundError``
        covers huggingface_hub (>=0.22), which raises a non-OSError on a
        local-only cache miss.
        """
        try:
            from huggingface_hub.errors import LocalEntryNotFoundError  # noqa: PLC0415 — optional-feature probe: ImportError here is a handled degraded mode
        except ImportError:
            return (OSError,)
        else:
            return (OSError, LocalEntryNotFoundError)

    def _construct_model(self, device: str, cache_folder: str | None, local: bool):
        """Build one ``SentenceTransformer``. Import is at call time so the
        ``sentence_transformers.SentenceTransformer`` patch point still works.

        ``local`` toggles ``local_files_only=True`` — hermetic (no HF Hub
        requests) when the model is already cached. It must be an explicit
        kwarg, not HF_HUB_OFFLINE, which hub freezes into module constants at
        first import (reproduced 2026-07-03). source: kwarg added in
        sentence-transformers v3.0.0.
        """
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415 — optional dependency (sentence-transformers (multi-second model load)); imported where used so environments without it keep working

        kwargs: dict[str, Any] = {
            "device": device,
            "revision": self._revision,
            # explicit, XDG-aware default (mirrors reranker bb1c581f) unless the
            # user already set HF_HOME / SENTENCE_TRANSFORMERS_HOME (issue #124).
            "cache_folder": cache_folder,
        }
        if local:
            kwargs["local_files_only"] = True
        return SentenceTransformer(self._model_name, **kwargs)

    def _finalize_loaded(self, device: str) -> None:
        """Reconcile the model's real dimension and record the LOADED state."""
        # sentence-transformers 5.x renamed get_sentence_embedding_dimension →
        # get_embedding_dimension. Prefer the new name; fall back for <5.
        get_dim = getattr(
            self._model,
            "get_embedding_dimension",
            self._model.get_sentence_embedding_dimension,
        )
        actual_dim = get_dim()
        if actual_dim != self._dim:
            self._dim = actual_dim
        self._model_state = ModelState.LOADED
        logger.info(
            "Loaded embedding model: %s (%dD, device=%s)",
            self._model_name,
            self._dim,
            device,
        )

    def _load_model(self, device: str) -> None:
        """Load the model, moving through the explicit lifecycle states.

        Never blocks and never crashes the caller (issue #169): a cache miss
        (MODEL_FILES_ABSENT) or an unexpected construction failure (LOAD_RAISED)
        engages the download-free fallback for THIS session and kicks off a
        background fetch so the next session is neural. Only ``ImportError``
        (PACKAGE_ABSENT) escapes, handled by ``_ensure_model``.
        """
        cache_folder = embedding_cache_dir()
        try:
            self._model = self._construct_model(device, cache_folder, local=True)
        except self._cache_miss_types():
            # MODEL_FILES_ABSENT: package present, weights not cached yet.
            self._engage_fallback(
                ModelState.MODEL_FILES_ABSENT,
                "embedding model files not cached; downloading in background",
            )
            trigger_background_model_download(
                self._model_name, self._revision, cache_folder
            )
            return
        except ImportError:
            raise  # PACKAGE_ABSENT — handled by _ensure_model
        except Exception as exc:  # noqa: BLE001 — corrupt cache / unexpected — do NOT crash
            self._engage_fallback(
                ModelState.LOAD_RAISED, f"embedding model load failed: {exc}"
            )
            return
        self._finalize_loaded(device)

    def _ensure_model(self) -> None:
        if self._model is not None or self._unavailable:
            return
        try:
            self._load_model(self._resolve_device())
        except ImportError:
            # PACKAGE_ABSENT: sentence-transformers is not installed.
            self._engage_fallback(
                ModelState.PACKAGE_ABSENT, "sentence-transformers not installed"
            )
            trigger_background_install()

    def _engage_fallback(self, state: ModelState, reason: str) -> None:
        """Record a non-LOADED lifecycle state and LOUDLY engage the fallback.

        precondition: called from the load path when the neural model cannot be
        served this session.
        postcondition: ``model_state`` is ``state`` and ``_unavailable`` is True;
        exactly one WARNING is logged (issue #169) so the degrade is never
        silent — the factory then routes encode() to the algorithmic provider.
        """
        self._model_state = state
        self._unavailable = True
        logger.warning(
            "Embedding fallback ENGAGED (%s): using deterministic download-free "
            "algorithmic embeddings (issue #169) — lower fidelity than "
            "sentence-transformers, upgrades automatically once the model is "
            "present. Fallback vectors are tagged 'fallback' and never "
            "cross-rank against neural vectors.",
            reason,
        )
