"""Torch-free query encoder for the automatic-recall hook (issue #706).

Loading sentence-transformers costs 15-22 s in a fresh process (measured
2026-10-29 on the owner's Mac) against the hook's 5 s budget. The pinned
all-MiniLM-L6-v2 revision also ships ``onnx/model.onnx``; with its
``tokenizer.json`` it reproduces the stored vectors (cosine >= 0.99999 on the
parity fixture) in about 0.5 s. Files are read from the local Hugging Face
cache only; ``download_query_encoder`` is the explicit fetch.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np

from mcp_server.infrastructure.embedding_model_lifecycle import (
    DEFAULT_MODEL_REVISION,
    embedding_cache_dir,
)

logger = logging.getLogger(__name__)

# source: sentence-transformers resolves the engine's "all-MiniLM-L6-v2" here.
_REPOSITORY = "sentence-transformers/all-MiniLM-L6-v2"
# source: pinned revision's file listing (huggingface_hub.list_repo_files).
_FILES = ("tokenizer.json", "onnx/model.onnx")
# source: sentence_bert_config.json max_seq_length at the pinned revision.
_MAX_TOKENS = 256

QueryEncoder = Callable[[str], np.ndarray]
# query text, stored vectors by memory id -> cosine by memory id
QueryScorer = Callable[[str, Mapping[int, Any]], dict[int, float]]


def _cached_paths() -> list[str] | None:
    """Local paths of both files at the pinned revision, or None if absent."""
    from huggingface_hub import try_to_load_from_cache  # noqa: PLC0415 -- optional ML dependency

    paths = [
        try_to_load_from_cache(
            _REPOSITORY,
            name,
            revision=DEFAULT_MODEL_REVISION,
            cache_dir=embedding_cache_dir(),
        )
        for name in _FILES
    ]
    if all(isinstance(path, str) for path in paths):
        return [str(path) for path in paths]
    return None


def _build(tokenizer_path: str, model_path: str) -> QueryEncoder:
    import onnxruntime  # noqa: PLC0415 -- optional ML dependency
    from tokenizers import Tokenizer  # noqa: PLC0415 -- optional ML dependency

    tokenizer = Tokenizer.from_file(tokenizer_path)
    tokenizer.enable_truncation(_MAX_TOKENS)
    session = onnxruntime.InferenceSession(
        model_path, providers=["CPUExecutionProvider"]
    )
    inputs = {item.name for item in session.get_inputs()}

    def encode(text: str) -> np.ndarray:
        encoding = tokenizer.encode(text)
        ids = np.array([encoding.ids], dtype=np.int64)
        mask = np.array([encoding.attention_mask], dtype=np.int64)
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in inputs:
            feeds["token_type_ids"] = np.zeros_like(ids)
        hidden = session.run(None, feeds)[0]
        # Mean pooling over real tokens, then L2 norm (the model's modules.json).
        pooled = (hidden * mask[..., None]).sum(axis=1)[0] / mask.sum()
        return (pooled / np.linalg.norm(pooled)).astype(np.float32)

    return encode


def cached_query_encoder() -> QueryEncoder | None:
    """An encoder built from cached files, or None when it cannot be served.

    Never downloads. None covers absent packages, absent files and load errors;
    the caller reports the degradation.
    """
    try:
        paths = _cached_paths()
        if paths is None:
            return None
        return _build(*paths)
    except Exception as exc:  # noqa: BLE001 -- optional model; caller degrades to lexical
        logger.warning("hook query encoder unavailable: %s", exc)
        return None


def _as_vector(value: Any) -> np.ndarray:
    """Stored SQLite bytes or a PostgreSQL real[] as float32."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return np.frombuffer(bytes(value), dtype=np.float32)
    return np.asarray(value, dtype=np.float32)


def scorer_from_encoder(encode: QueryEncoder) -> QueryScorer:
    """Cosine of the encoded query with each stored vector of its width."""

    def score(query: str, stored: Mapping[int, Any]) -> dict[int, float]:
        vector = encode(query)
        norm = float(np.linalg.norm(vector))
        result: dict[int, float] = {}
        for mid, raw in stored.items():
            other = _as_vector(raw)
            scale = norm * float(np.linalg.norm(other))
            if other.shape == vector.shape and scale > 0.0:
                result[mid] = float(np.dot(vector, other) / scale)
        return result

    return score


def cached_query_scorer() -> QueryScorer | None:
    """A similarity scorer over the cached encoder, or None when absent."""
    encoder = cached_query_encoder()
    return None if encoder is None else scorer_from_encoder(encoder)


def download_query_encoder() -> None:
    """Fetch both files at the pinned revision; raises the real error."""
    from huggingface_hub import hf_hub_download  # noqa: PLC0415 -- optional ML dependency

    for name in _FILES:
        hf_hub_download(
            _REPOSITORY,
            name,
            revision=DEFAULT_MODEL_REVISION,
            cache_dir=embedding_cache_dir(),
        )


__all__ = [
    "QueryEncoder",
    "QueryScorer",
    "cached_query_encoder",
    "cached_query_scorer",
    "download_query_encoder",
    "scorer_from_encoder",
]
