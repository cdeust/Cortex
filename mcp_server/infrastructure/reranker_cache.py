"""Filesystem boundary for the FlashRank reranker's on-disk model cache.

core/reranker_model.py may not import os/pathlib or perform I/O (issue
#560); every filesystem touch (cache-dir resolution honoring
$XDG_CACHE_HOME/$HOME, model-file existence check, sha256 of the on-disk
weights) lives here instead. Wired into core via
``configure_reranker_filesystem`` (mcp_server.hooks.wiring in production,
tests_py/conftest.py for the test session) — same idiom as
mcp_server.core.environment.

source: ADR-0244 (issue #560)
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from mcp_server.shared.platform import cache_dir as _base_cache_dir


def reranker_cache_dir() -> str:
    """Durable on-disk cache directory for the FlashRank ONNX model.

    source: ADR-0244"""
    return str(_base_cache_dir() / "flashrank")


def reranker_model_exists(model_path: str) -> bool:
    """True iff the ONNX weights file at ``model_path`` is present on disk.

    source: ADR-0244"""
    return Path(model_path).is_file()


def reranker_model_sha256(model_path: str) -> str | None:
    """Sha256 of the on-disk ONNX weights file at ``model_path``, or None
    if it is absent.

    source: ADR-0244"""
    path = Path(model_path)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
