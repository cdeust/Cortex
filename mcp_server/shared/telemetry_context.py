"""Request-local retrieval measurements; no changes to ranking or responses.

source: ADR-0668"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import perf_counter


@dataclass
class RetrievalMetrics:
    """Actual dispatch route, passages scored by the model, time per stage.

    ``stage_ms`` maps a stage name to the wall-clock milliseconds spent in it
    during this operation (issue #722: a latency breakdown of public recall).
    """

    tier: str | None = None
    reranked_count: int = 0
    stage_ms: dict[str, float] = field(default_factory=dict)


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


@contextmanager
def timed_stage(name: str) -> Iterator[None]:
    """Add the wall-clock time of the enclosed block to ``stage_ms[name]``.

    A stage entered twice accumulates. Outside an operation the block runs and
    nothing is recorded. The time is recorded even when the block raises, so a
    failed stage still shows where the operation spent its time.

    source: issue #722 (measure each recall stage before choosing an optimization)
    """
    current = _metrics.get()
    if current is None:
        yield
        return
    started = perf_counter()
    try:
        yield
    finally:
        # source: ADR-0326 (perf_counter seconds, telemetry milliseconds)
        elapsed_ms = (perf_counter() - started) * 1000.0
        current.stage_ms[name] = current.stage_ms.get(name, 0.0) + elapsed_ms
