"""`cortex doctor` check: are the cached embedding weights intact (#734).

The embedding revision is pinned, but nothing hashed the weights the engine
loads (docs/audits/model-identity-inventory-2026-11-06.md). This check reads
the ``model.safetensors`` entry of the pinned snapshot and compares its sha256
with the digest its blob is named by, the one the Hub declared at download
(``core.embedding_weights_identity.classify_weights``).

The check is optional: without the model, recall serves the download-free
fallback embedding, so neither an absent nor a different file stops Cortex.
It reads the file only; it never downloads, deletes or loads a model.

source: docs/audits/model-identity-inventory-2026-11-06.md, remaining slice 3
"""

from __future__ import annotations

from typing import Any, Callable

from mcp_server.core.embedding_weights_identity import (
    ABSENT,
    UNVERIFIABLE,
    VERIFIED,
    classify_weights,
)
from mcp_server.infrastructure.embedding_model_lifecycle import DEFAULT_MODEL_REVISION
from mcp_server.infrastructure.embedding_weights_cache import (
    embedding_hub_cache,
    file_sha256,
    linked_blob_name,
    repo_cache_dir,
    weights_path,
)

NAME = "Embedding weights identity"  # source: issue #734 (acceptance criterion 3)
# source: EmbeddingEngine.__init__ default model_name, the one
# embedding_factory.get_embedding_engine constructs.
MODEL_NAME = "all-MiniLM-L6-v2"
_ABSENT_FIX = (
    "Run one recall with network access: the engine downloads revision "
    "{revision} into {cache} in the background (not when "
    "CORTEX_EMBEDDING_ZERO_DOWNLOAD is set)"
)
_MISMATCH_FIX = (
    "Remove the directory {repo_dir} and let the engine download the revision "
    "again; vectors written with this file are not comparable with the "
    "published numbers"
)


def embedding_identity(check: Callable[..., Any]) -> Any:
    """precondition: ``check`` builds a doctor ``Check`` from
        ``(name, ok, detail, fix, optional=...)``.
    postcondition: OK when the weights digest equals the sha256 their blob is
        named by; an optional warning naming the path when the file is absent,
        or is a copy that carries no declared digest, and naming both digests
        when they differ. An unreadable file is a warning, never raised."""
    cache = embedding_hub_cache()
    repo_dir = repo_cache_dir(cache, MODEL_NAME)
    path = weights_path(repo_dir, DEFAULT_MODEL_REVISION)
    try:
        identity = classify_weights(linked_blob_name(path), file_sha256(path))
    except OSError as exc:
        detail = f"cannot read {path}: {type(exc).__name__}: {exc}"
        return check(NAME, False, detail, "", optional=True)
    if identity.state == VERIFIED:
        detail = f"sha256 {identity.sha256} matches the digest the Hub declared"
        return check(NAME, True, detail, "", optional=True)
    if identity.state == ABSENT:
        detail = f"absent at {path}; recall serves the fallback embedding"
        fix = _ABSENT_FIX.format(revision=DEFAULT_MODEL_REVISION, cache=cache)
        return check(NAME, False, detail, fix, optional=True)
    if identity.state == UNVERIFIABLE:
        detail = (
            f"{path} is a copy, not a link to a blob named by its digest; "
            f"its sha256 is {identity.sha256}"
        )
        return check(NAME, False, detail, "", optional=True)
    detail = (
        f"sha256 {identity.sha256} at {path} differs from the "
        f"{identity.expected} the Hub declared"
    )
    fix = _MISMATCH_FIX.format(repo_dir=repo_dir)
    return check(NAME, False, detail, fix, optional=True)
