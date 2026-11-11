"""The embedding model a benchmark run served, for its manifests.

Issue #734, slice 2. ``EmbeddingEngine.revision`` is the pin the engine was
constructed with, whatever its load state: a run in ``PACKAGE_ABSENT`` serves
the algorithmic fallback and still reports the pinned revision
(docs/audits/model-identity-inventory-2026-11-06.md, probe at ``79bd6c3``).
These fields record what was served instead: the mode, the ``ModelState``,
the model name, and the revision and device only when the state is ``LOADED``.
The device is the one the model was loaded on (``device_served``), not the
setting: ``auto`` and a GPU failure that reloads on CPU both differ from it
(issue #734, slice 7).

source: docs/audits/model-identity-inventory-2026-11-06.md, remaining slice 1
"""

from __future__ import annotations

from typing import Any

_UNRESOLVED = "unresolved"


def embedding_identity_fields(engine: Any) -> dict[str, Any]:
    """Identity fields of ``engine`` as it serves now.

    precondition: ``engine`` exposes ``mode``, ``model_state``, ``model_name``,
        ``revision`` and ``device_served`` like ``EmbeddingEngine``.
    postcondition: ``mode`` is read first, so the load has been attempted and
        ``model_state`` is final for this process. ``embedding_model_revision``
        is the pinned revision when the state is ``LOADED`` and None otherwise:
        no bytes of that revision were loaded, so the run cannot name one.
        ``embedding_device`` follows the same rule: the algorithmic fallback
        runs on no model device.
    """
    mode = engine.mode
    state = engine.model_state
    loaded = state.name == "LOADED"
    return {
        "embedding_mode": mode,
        "embedding_model_state": state.name,
        "embedding_model_name": engine.model_name,
        "embedding_model_revision": engine.revision if loaded else None,
        "embedding_device": engine.device_served if loaded else None,
    }


def embedding_manifest_fields() -> dict[str, Any]:
    """``embedding_identity_fields`` of the process engine, or ``unresolved``.

    The except arm is the recorded degraded mode: an engine that cannot be
    built is written as ``unresolved`` in every field rather than aborting the
    manifest (same contract as ``reranker_fields``, ADR-0091).
    """
    try:
        # noqa: PLC0415 — ImportError-probe boundary: the except arm IS the
        # degraded mode ("unresolved" in the manifest).
        from mcp_server.infrastructure.embedding_factory import (  # noqa: PLC0415
            get_embedding_engine,
        )

        return embedding_identity_fields(get_embedding_engine())
    except Exception:  # noqa: BLE001 — signal is the recorded "unresolved" value
        return {
            "embedding_mode": _UNRESOLVED,
            "embedding_model_state": _UNRESOLVED,
            "embedding_model_name": None,
            "embedding_model_revision": None,
            "embedding_device": None,
        }
