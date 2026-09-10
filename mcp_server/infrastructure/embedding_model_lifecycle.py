"""Model lifecycle for the embedding engine — device + load state machine.

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

source: ADR-0523"""

from __future__ import annotations

import enum
import logging
import os
from typing import Any

from mcp_server.infrastructure.embedding_downloads import (
    trigger_background_install,
    trigger_background_model_download,
)
from mcp_server.infrastructure.embedding_prefix import BertPrefix
from mcp_server.shared.platform import cache_dir as _base_cache_dir

# source: ADR-0523
DEFAULT_MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"

logger = logging.getLogger(__name__)


class ModelState(enum.Enum):
    """Explicit lifecycle states of the neural model load.

    source: ADR-0523"""

    UNINITIALIZED = enum.auto()
    LOADED = enum.auto()
    PACKAGE_ABSENT = enum.auto()
    MODEL_FILES_ABSENT = enum.auto()
    LOAD_RAISED = enum.auto()


def embedding_cache_dir() -> str | None:
    """Resolve the ``cache_folder`` to pass to ``SentenceTransformer``.

    source: ADR-0523"""
    if os.environ.get("HF_HOME") or os.environ.get("SENTENCE_TRANSFORMERS_HOME"):
        return None
    return str(_base_cache_dir() / "huggingface" / "hub")


class _EmbeddingLifecycleMixin:
    """Device resolution + the neural-model load state machine.

    source: ADR-0523"""

    _model: Any
    _prefix_guard: BertPrefix | None = None
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

            return (OSError, LocalEntryNotFoundError)
        except ImportError:
            return (OSError,)

    def _construct_model(self, device: str, cache_folder: str | None, local: bool):
        """Build one ``SentenceTransformer``.

        source: ADR-0523"""
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415 — optional dependency (sentence-transformers (multi-second model load)); imported where used so environments without it keep working

        kwargs: dict[str, Any] = {
            "device": device,
            "revision": self._revision,
            # source: ADR-0523
            "cache_folder": cache_folder,
        }
        if local:
            kwargs["local_files_only"] = True
        return SentenceTransformer(self._model_name, **kwargs)

    def _finalize_loaded(self, device: str) -> None:
        """Reconcile the model's real dimension and record the LOADED state."""
        # source: ADR-0523
        get_dim = getattr(
            self._model,
            "get_embedding_dimension",
            self._model.get_sentence_embedding_dimension,
        )
        actual_dim = get_dim()
        if actual_dim != self._dim:
            self._dim = actual_dim
        self._prefix_guard = BertPrefix.for_model(self._model)
        self._model_state = ModelState.LOADED
        logger.info(
            "Loaded embedding model: %s (%dD, device=%s)",
            self._model_name,
            self._dim,
            device,
        )

    def _load_model(self, device: str) -> None:
        """Load the model, moving through the explicit lifecycle states.

        source: ADR-0523"""
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
                postcondition: ``model_state`` is ``state`` and ``_unavailable`` is
                True;
                exactly one WARNING is logged  so the degrade is never
                silent — the factory then routes encode() to the algorithmic provider.

        source: ADR-0523"""
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
