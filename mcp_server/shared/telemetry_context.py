"""Request-local retrieval measurements; no changes to ranking or responses.

source: ADR-0668"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class RetrievalMetrics:
    """Actual dispatch route and passages successfully scored by the model."""

    tier: str | None = None
    reranked_count: int = 0


_metrics: ContextVar[RetrievalMetrics | None] = ContextVar(
    "cortex_retrieval_metrics", default=None
)


@contextmanager
def operation_metrics() -> Iterator[RetrievalMetrics]:
    """Start an independent operation and restore its caller on every exit."""
    current = RetrievalMetrics()
    token = _metrics.set(current)
    try:
        yield current
    finally:
        _metrics.reset(token)


def retrieval_metrics() -> RetrievalMetrics:
    """Return recorded work, or an empty measurement outside an operation."""
    current = _metrics.get()
    return current if current is not None else RetrievalMetrics()


def set_retrieval_tier(tier: str) -> None:
    """Record the route actually executed, rather than inferring from intent.

    source: ADR-0668
    """
    current = _metrics.get()
    if current is not None:
        current.tier = tier


def count_reranked(count: int) -> None:
    """Count successful model work; skipped/failed inference contributes zero."""
    current = _metrics.get()
    if current is not None:
        current.reranked_count += count
