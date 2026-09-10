"""One encoder batch with explicit per-item recovery for best-effort writers.

source: ADR-0517"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EncodedItem:
    item: dict
    embedding: Any = None
    error: Exception | None = None

    def value(self) -> Any:
        if self.error is not None:
            raise self.error
        return self.embedding


def _collect_inputs(items: list[dict], content_key: str) -> tuple[list, list, list]:
    results = [EncodedItem(item) for item in items]
    positions, texts = [], []
    for index, result in enumerate(results):
        try:
            text = result.item[content_key]
            if text:
                positions.append(index)
                texts.append(text)
        except Exception as exc:  # noqa: BLE001 — retain the writer's per-item error boundary
            result.error = exc
    return results, positions, texts


def _retry_items(results: list, positions: list, texts: list, engine: Any) -> None:
    for index, text in zip(positions, texts, strict=True):
        try:
            results[index].embedding = engine.encode(text)
        except Exception as exc:  # noqa: BLE001 — caller logs this individual failure as before
            results[index].error = exc


def encode_items(items: list[dict], content_key: str, engine: Any) -> list[EncodedItem]:
    """Keep item/vector/error correspondence and scalar None for empty inputs."""
    results, positions, texts = _collect_inputs(items, content_key)
    if not texts:
        return results
    try:
        encoded = engine.encode_batch(texts)
        pairs = list(zip(positions, encoded, strict=True))
    except Exception:  # noqa: BLE001 — a batch failure must not discard unrelated valid rows
        logger.exception(
            "Embedding batch failed; retrying each item with scalar encode"
        )
        _retry_items(results, positions, texts, engine)
        return results
    for index, vector in pairs:
        results[index].embedding = vector
    return results
