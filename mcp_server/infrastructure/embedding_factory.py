"""source: ADR-0521"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_server.infrastructure.embedding_model_lifecycle import ModelState
from mcp_server.infrastructure.memory_config import get_memory_settings

if TYPE_CHECKING:
    from mcp_server.infrastructure.embedding_engine import EmbeddingEngine

# Process-wide singleton. Handlers/hooks read it via get_embedding_engine().
_singleton: EmbeddingEngine | None = None

# source: ADR-0521
_FALLBACK_STATES = frozenset(
    {
        ModelState.UNINITIALIZED,
        ModelState.PACKAGE_ABSENT,
        ModelState.MODEL_FILES_ABSENT,
        ModelState.LOAD_RAISED,
    }
)


def use_fallback(state: ModelState) -> bool:
    """postcondition: True for every non-``LOADED`` state; the mapping is total —
        ``LOADED`` → neural, everything else → fallback.

    source: ADR-0521"""
    return state in _FALLBACK_STATES


def current_embedding_mode() -> str:
    """Return the process-wide embedding provenance for telemetry .

        postcondition: ``"neural"`` / ``"fallback"`` if a singleton engine exists
        (resolving its model on first read), else ``"unknown"``. Does not construct
        an engine as a side effect.

    source: ADR-0521"""
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
