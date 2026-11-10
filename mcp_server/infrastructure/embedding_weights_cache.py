"""Filesystem boundary: where the pinned embedding weights sit in the cache.

Issue #734, slice 4. Resolves the ``model.safetensors`` entry of the pinned
snapshot the way ``EmbeddingEngine`` loads it (``SentenceTransformer`` with the
``cache_folder`` of ``embedding_cache_dir``), reads which blob it links to,
and hashes the bytes. It never downloads, deletes or loads a model.

source: docs/audits/model-identity-inventory-2026-11-06.md, remaining slice 3
"""

from __future__ import annotations

import hashlib
import os

from mcp_server.infrastructure.embedding_model_lifecycle import embedding_cache_dir

# source: sentence-transformers 5.7.0 and 6.0.1 (uv.lock), SentenceTransformer.
# default_huggingface_organization; base/model.py prefixes a model id that
# has no "/" with it. "all-MiniLM-L6-v2" is not in its
# ORIGINAL_TRANSFORMER_MODELS exception list.
_DEFAULT_ORGANIZATION = "sentence-transformers"
# source: transformers SAFE_WEIGHTS_NAME (4.57.6 and 5.21.0, uv.lock);
# SAFETENSORS_ONLY (embedding_model_lifecycle.py) loads only this file.
WEIGHTS_FILE = "model.safetensors"


def _hf_hub_cache() -> str:
    """``HF_HUB_CACHE`` as huggingface_hub constants.py resolves it.

    source: huggingface_hub 0.36.2 and 1.33.0 constants.py (HF_HOME,
    XDG_CACHE_HOME, HUGGINGFACE_HUB_CACHE, HF_HUB_CACHE)."""
    env = os.environ
    default_home = os.path.join(env.get("XDG_CACHE_HOME", "~/.cache"), "huggingface")
    home = os.path.expandvars(os.path.expanduser(env.get("HF_HOME", default_home)))
    legacy = env.get("HUGGINGFACE_HUB_CACHE", os.path.join(home, "hub"))
    return os.path.expandvars(os.path.expanduser(env.get("HF_HUB_CACHE", legacy)))


def embedding_hub_cache() -> str:
    """The hub cache the engine loads from: Cortex's own ``cache_folder``,
    else ``SENTENCE_TRANSFORMERS_HOME`` (read by sentence-transformers when
    ``cache_folder`` is None, base/model.py), else huggingface_hub's default.

    Normalized as hf_hub_download normalizes it before any lookup
    (huggingface_hub 1.33.0 file_download.py:
    ``str(Path(cache_dir).expanduser().resolve())``), so ``~/models`` names
    the directory the engine reads, not a literal ``~`` under the cwd."""
    cache = (
        embedding_cache_dir()
        or os.environ.get("SENTENCE_TRANSFORMERS_HOME")
        or _hf_hub_cache()
    )
    return os.path.realpath(os.path.expanduser(cache))


def repo_cache_dir(cache: str, model_name: str) -> str:
    """``models--<org>--<name>`` under ``cache`` (file_download.repo_folder_name)."""
    repo_id = (
        model_name if "/" in model_name else f"{_DEFAULT_ORGANIZATION}/{model_name}"
    )
    return os.path.join(cache, "--".join(["models", *repo_id.split("/")]))


def weights_path(repo_dir: str, revision: str) -> str:
    """The snapshot entry for ``revision`` (a commit hash names its folder)."""
    return os.path.join(repo_dir, "snapshots", revision, WEIGHTS_FILE)


def linked_blob_name(path: str) -> str | None:
    """Name of the blob ``path`` links to, or None when it is not a link."""
    if not os.path.islink(path):
        return None
    return os.path.basename(os.readlink(path))


def file_sha256(path: str) -> str | None:
    """Sha256 of the file ``path`` resolves to, or None when there is none."""
    if not os.path.isfile(path):
        return None
    # hashlib.file_digest (Python 3.11+, the floor in pyproject.toml) reads in
    # chunks itself, so no read size or sentinel is spelled out here.
    with open(path, "rb") as fh:
        return hashlib.file_digest(fh, hashlib.sha256).hexdigest()
