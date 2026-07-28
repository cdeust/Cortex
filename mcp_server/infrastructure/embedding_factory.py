"""Composition root for the embedding subsystem (Cortex#173, seam 3).

This is the "engine selection / wiring" seam: the single place that reads the
runtime settings (``EMBEDDING_DIM`` / ``EMBEDDING_DEVICE``) and assembles the
process-wide encoder. Consumers call ``get_embedding_engine()`` rather than
constructing an ``EmbeddingEngine`` themselves, which guarantees one model, one
device, no mixed-device embeddings, ~5x memory savings.

Keeping selection here — separate from the concrete providers
(``embedding_engine.EmbeddingEngine``, neural, and
``embedding_fallback_provider.AlgorithmicEmbeddingProvider``, download-free) and
their interface (``embedding_provider.EmbeddingProvider``) — is what lets the
active provider be chosen per ``ModelState`` (``use_fallback``) with no consumer
change (issue #169).

Import-cycle note: the concrete ``EmbeddingEngine`` (and ``get_memory_settings``)
are imported lazily *inside* ``get_embedding_engine`` so this module has no
module-load dependency on ``embedding_engine`` — ``embedding_engine`` re-exports
these functions, so the two modules must not import each other at top level.
``ModelState`` comes from ``embedding_model_lifecycle`` (no cycle).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_server.infrastructure.embedding_model_lifecycle import ModelState
from mcp_server.infrastructure.memory_config import get_memory_settings

if TYPE_CHECKING:
    from mcp_server.infrastructure.embedding_engine import EmbeddingEngine

# Process-wide singleton. Handlers/hooks read it via get_embedding_engine().
_singleton: EmbeddingEngine | None = None

# The state→provider selection (issue #169). Every ModelState that is not a
# loaded neural model routes to the download-free algorithmic fallback —
# PACKAGE_ABSENT, MODEL_FILES_ABSENT (download pending), LOAD_RAISED, and the
# not-yet-attempted UNINITIALIZED. NO state maps to nothing.
_FALLBACK_STATES = frozenset(
    {
        ModelState.UNINITIALIZED,
        ModelState.PACKAGE_ABSENT,
        ModelState.MODEL_FILES_ABSENT,
        ModelState.LOAD_RAISED,
    }
)


def use_fallback(state: ModelState) -> bool:
    """Whether ``state`` selects the algorithmic fallback provider (issue #169).

    postcondition: True for every non-``LOADED`` state; the mapping is total —
    ``LOADED`` → neural, everything else → fallback.
    """
    return state in _FALLBACK_STATES


def current_embedding_mode() -> str:
    """Return the process-wide embedding provenance for telemetry (issue #169).

    postcondition: ``"neural"`` / ``"fallback"`` if a singleton engine exists
    (resolving its model on first read), else ``"unknown"``. Does not construct
    an engine as a side effect.
    """
    if _singleton is None:
        return "unknown"
    return _singleton.mode


def get_embedding_engine() -> "EmbeddingEngine":
    """Return the process-wide EmbeddingEngine singleton, building it once.

    precondition: none.
    postcondition: the same instance is returned for every call until
    ``reset_embedding_engine`` clears it; the instance is constructed from the
    current ``MemorySettings`` (dimension + device).
    """
    global _singleton
    if _singleton is None:
        from mcp_server.infrastructure.embedding_engine import EmbeddingEngine  # noqa: PLC0415 — import cycle with mcp_server.infrastructure.embedding_engine; a top-level import fails at boot

        s = get_memory_settings()
        _singleton = EmbeddingEngine(dim=s.EMBEDDING_DIM, device=s.EMBEDDING_DEVICE)
    return _singleton


def reset_embedding_engine() -> None:
    """Clear the singleton (for testing only)."""
    global _singleton
    _singleton = None
