"""One effective runtime manifest: which code and models a local run uses (#734).

Issue #734, slice 5. The facts that identify a run were spread over five
surfaces, each with a part (docs/audits/model-identity-inventory-2026-11-06.md,
"Where each fact is exposed"): the artifact check (#729), the two weights
identity checks, the backend marker, and the embedding fields of the benchmark
manifests. ``effective_manifest`` joins them in one dictionary, built here
only, that ``cortex-doctor manifest`` prints and both benchmark manifests
embed under ``runtime_manifest``.

What it holds, and what it leaves out:

- ``artifact``: kind, version, git revision, whether it differs from what
  names it, and the members digest (``doctor_artifact.identify``). Not its
  location: a path names the user's home directory.
- ``backend``: the backend the precedence chain selects (``effective_backend``),
  never ``DATABASE_URL`` or any other connection setting.
- ``embedding`` and ``reranker``: model name, pinned revision or expected
  digest, the identity of the weights on disk (``classify_weights``,
  ``classify_model_digest``), never their path. ``served`` is what the caller's
  engine served (mode, ``ModelState``, revision when loaded): a benchmark
  passes it; ``cortex-doctor`` loads no model, so it writes None.

It reads files only: it never downloads, loads or deletes a model.

source: docs/audits/model-identity-inventory-2026-11-06.md, remaining slice 2
"""

from __future__ import annotations

import os
from typing import Any

from mcp_server.core.embedding_weights_identity import classify_weights
from mcp_server.core import reranker_model
from mcp_server.core.reranker_identity import EXPECTED_MODEL_SHA256
from mcp_server.core.reranker_identity import classify_model_digest
from mcp_server.doctor_artifact import identify
from mcp_server.doctor_embedding import MODEL_NAME as EMBEDDING_MODEL_NAME
from mcp_server.infrastructure.backend_marker import (
    BackendMarkerError,
    effective_backend,
)
from mcp_server.infrastructure.embedding_model_lifecycle import DEFAULT_MODEL_REVISION
from mcp_server.infrastructure.embedding_weights_cache import (
    embedding_hub_cache,
    file_sha256,
    linked_blob_name,
    repo_cache_dir,
    weights_path,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.reranker_cache import (
    reranker_cache_dir,
    reranker_model_sha256,
)

# source: issue #734; bumped when a key changes meaning, so a reader of
# committed manifests can tell two layouts apart.
SCHEMA = 1
# source: backend_marker.effective_backend postcondition ("" when nothing is
# configured or a database URL is: the engine default ``auto`` applies).
ENGINE_DEFAULT = "auto"
UNREADABLE = "unreadable"  # source: issue #734 (a file exists, cannot be read)


def _failure(exc: BaseException) -> str:
    """The error class only: a message can carry a path or a setting."""
    return f"{UNREADABLE}: {type(exc).__name__}"


def artifact_section() -> dict[str, Any]:
    """The running ``mcp_server`` as ``doctor_artifact.identify`` names it.

    postcondition: ``modified`` is True when a member or a bytecode file
        differs from what names the artifact; ``unknown`` says why the
        identity cannot be stated, or None. Never raises on an unreadable
        file: ``kind`` is None and ``unknown`` names the error class."""
    try:
        found = identify()
    except (OSError, RuntimeError, ValueError) as exc:
        return {"kind": None, "unknown": _failure(exc)}
    return {
        "kind": found.kind,
        "version": found.version,
        "revision": found.revision,
        "modified": found.modified or bool(found.altered),
        "digest": found.digest,
        "unknown": found.unknown,
    }


def backend_section() -> str:
    """``sqlite``, ``postgresql``, ``auto`` when the chain leaves the choice to
    the engine, or ``unreadable: BackendMarkerError``."""
    try:
        return effective_backend(os.environ) or ENGINE_DEFAULT
    except BackendMarkerError as exc:
        return _failure(exc)


def embedding_section(served: dict[str, Any] | None) -> dict[str, Any]:
    """The embedding model: pinned identity, weights on disk, what was served."""
    repo_dir = repo_cache_dir(embedding_hub_cache(), EMBEDDING_MODEL_NAME)
    path = weights_path(repo_dir, DEFAULT_MODEL_REVISION)
    try:
        found = classify_weights(linked_blob_name(path), file_sha256(path))
        weights = {"state": found.state, "sha256": found.sha256}
    except OSError as exc:
        weights = {"state": _failure(exc), "sha256": None}
    return {
        "name": EMBEDDING_MODEL_NAME,
        "pinned_revision": DEFAULT_MODEL_REVISION,
        "device_requested": get_memory_settings().EMBEDDING_DEVICE,
        "weights": weights,
        "served": served,
    }


def reranker_section(served: dict[str, Any] | None) -> dict[str, Any]:
    """The reranker model: expected digest, weights on disk, what was served."""
    path = reranker_model.model_path_under(reranker_cache_dir())
    try:
        found = classify_model_digest(reranker_model_sha256(path))
        weights = {"state": found.state, "sha256": found.sha256}
    except OSError as exc:
        weights = {"state": _failure(exc), "sha256": None}
    return {
        # Read at call time: benchmarks/reranker_matrix patches these per cell.
        "name": reranker_model._MODEL_NAME,
        "file": reranker_model._MODEL_FILE,
        "expected_sha256": EXPECTED_MODEL_SHA256,
        "weights": weights,
        "served": served,
    }


def effective_manifest(
    embedding_served: dict[str, Any] | None = None,
    reranker_served: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The one manifest of this run, JSON-serialisable.

    precondition: ``embedding_served`` and ``reranker_served`` are the fields
        the caller's own engines reported, or None when it served no model.
    postcondition: keys ``schema``, ``artifact``, ``backend``, ``embedding``,
        ``reranker``; no path, URL, memory content or connection setting."""
    return {
        "schema": SCHEMA,
        "artifact": artifact_section(),
        "backend": backend_section(),
        "embedding": embedding_section(embedding_served),
        "reranker": reranker_section(reranker_served),
    }
