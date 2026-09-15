"""FlashRank model identity, cache location, and the offline-fetch gate.

Real filesystem touches (cache-dir resolution, existence check, sha256 of
the on-disk weights) are injected from
mcp_server/infrastructure/reranker_cache.py via
``configure_reranker_filesystem`` — core is zero-I/O (issue #560). Path
*composition* (this module's own string join of cache_dir + name + file)
stays here since it is pure and needs to stay patchable by
benchmarks/reranker_matrix/runtime.py's per-cell attribute patching of
``_MODEL_NAME``/``_MODEL_FILE``/``reranker_cache_dir``.

source: ADR-0244"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from mcp_server.core.environment import read_environment_variable

# source: ADR-0244


_MODEL_NAME = "ms-marco-MiniLM-L-12-v2"
_MODEL_FILE = "flashrank-MiniLM-L-12-v2_Q.onnx"
_OFFLINE_ENV = "CORTEX_RERANKER_OFFLINE"

CacheDirProvider = Callable[[], str]
ModelExistsProvider = Callable[[str], bool]
ModelSha256Provider = Callable[[str], "str | None"]

_cache_dir_provider: CacheDirProvider | None = None
_model_exists_provider: ModelExistsProvider | None = None
_model_sha256_provider: ModelSha256Provider | None = None


def configure_reranker_filesystem(
    *,
    cache_dir: CacheDirProvider,
    model_exists: ModelExistsProvider,
    model_sha256: ModelSha256Provider,
) -> None:
    """Composition-root hook: register the real cache-filesystem operations.

    source: ADR-0244 (issue #560: core/ may not import os/pathlib)"""
    global _cache_dir_provider, _model_exists_provider, _model_sha256_provider
    _cache_dir_provider = cache_dir
    _model_exists_provider = model_exists
    _model_sha256_provider = model_sha256


def _unconfigured(what: str) -> RuntimeError:
    return RuntimeError(
        f"reranker {what} provider not configured — call "
        "configure_reranker_filesystem() at the composition root first"
    )


def reranker_cache_dir() -> str:
    """Durable on-disk cache directory for the FlashRank ONNX model.

    source: ADR-0244"""
    if _cache_dir_provider is None:
        raise _unconfigured("cache_dir")
    return _cache_dir_provider()


def _model_path() -> str:
    return f"{reranker_cache_dir()}/{_MODEL_NAME}/{_MODEL_FILE}"


def _model_exists() -> bool:
    """True iff the ONNX weights file is present on disk right now.

    source: ADR-0244"""
    if _model_exists_provider is None:
        raise _unconfigured("model_exists")
    return _model_exists_provider(_model_path())


def model_sha256() -> str | None:
    """Sha256 of the on-disk ONNX weights file, or None if it is absent.

    source: ADR-0244"""
    if _model_sha256_provider is None:
        raise _unconfigured("model_sha256")
    return _model_sha256_provider(_model_path())


def _offline_requested() -> bool:
    """True when the caller has forbidden a network fetch of the model.

    Precondition: none.
    Postcondition: True iff CORTEX_RERANKER_OFFLINE is set to a value other
    than empty, 0, false, or no, ignoring whitespace and case. Unset is False.
    source: ADR-0244"""
    raw = read_environment_variable(_OFFLINE_ENV) or ""
    return raw.strip().lower() not in ("", "0", "false", "no")


@dataclass(frozen=True)
class RerankerStatus:
    """Snapshot of the FlashRank reranker singleton's load state.

    source: ADR-0244"""

    state: str
    model_path: str
    error: str | None = None
