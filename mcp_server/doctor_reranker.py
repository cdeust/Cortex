"""`cortex doctor` check: are the reranker weights the published ones (#734).

The FlashRank ONNX file is downloaded by name, and its sha256 was recorded in
benchmark manifests without being compared with anything
(docs/audits/model-identity-inventory-2026-11-06.md). This check reads the
file FlashRank would load from the durable cache and classifies its digest
with ``core.reranker_identity.classify_model_digest``.

The check is optional: recall runs without the reranker (first-stage scores),
so neither an absent nor a different file stops Cortex. It reads the file
only; it never downloads, deletes or loads a model.

source: docs/audits/model-identity-inventory-2026-11-06.md, remaining slice 3
"""

from __future__ import annotations

from typing import Any, Callable

from mcp_server.core.reranker_identity import ABSENT, VERIFIED, classify_model_digest
from mcp_server.core.reranker_model import model_path_under
from mcp_server.infrastructure.reranker_cache import (
    reranker_cache_dir,
    reranker_model_sha256,
)

NAME = "Reranker weights identity"  # source: issue #734 (acceptance criterion 3)
_ABSENT_FIX = (
    "Run one recall with network access (FlashRank downloads the model into "
    "this cache), or provision the file there before setting "
    "CORTEX_RERANKER_OFFLINE"
)
_MISMATCH_FIX = (
    "Delete {path} and let FlashRank download it again; results measured with "
    "this file are not comparable with the published numbers"
)


def reranker_identity(check: Callable[..., Any]) -> Any:
    """precondition: ``check`` builds a doctor ``Check`` from
        ``(name, ok, detail, fix, optional=...)``.
    postcondition: OK when the on-disk digest equals the pinned one; an
        optional warning naming the path when the file is absent, and naming
        both digests when they differ. An unreadable file is reported as a
        warning with the error, never raised."""
    path = model_path_under(reranker_cache_dir())
    try:
        identity = classify_model_digest(reranker_model_sha256(path))
    except OSError as exc:
        detail = f"cannot read {path}: {type(exc).__name__}: {exc}"
        return check(NAME, False, detail, "", optional=True)
    if identity.state == VERIFIED:
        detail = f"sha256 {identity.sha256} matches the published results"
        return check(NAME, True, detail, "", optional=True)
    if identity.state == ABSENT:
        detail = f"absent at {path}; recall runs without reranking"
        return check(NAME, False, detail, _ABSENT_FIX, optional=True)
    detail = (
        f"sha256 {identity.sha256} at {path} differs from the expected "
        f"{identity.expected}"
    )
    return check(NAME, False, detail, _MISMATCH_FIX.format(path=path), optional=True)
