"""Invariant I10 — pool capacity respects registered cycle workers.

Formal predicate (from docs/invariants/cortex-invariants.md):

    pool.max >= |{registered cycle workers}| + 1

The +1 reserves a slot for the hot/read path so a running consolidate
cannot starve an interactive recall that arrives mid-cycle.

Phase 5 refinement: the two-pool model (interactive + batch) means
this invariant applies per-pool:

    interactive_pool.max_size >= interactive_tools + 1
    batch_pool.max_size       >= batch_cycle_workers + 1

In practice:
  * interactive_pool defaults to max=8 — far above the handful of
    concurrent recall/remember calls we serve per second.
  * batch_pool defaults to max=2 — room for one active consolidate
    AND one overlapping wiki_pipeline, with the +1 slot implicit in
    the admission semaphore backpressure (consolidate has
    Semaphore(1), so only one tries to acquire at a time).

Source:
  * docs/invariants/cortex-invariants.md §I10
  * docs/program/phase-5-pool-admission-design.md §1.1, §3
  * ADR-0045 R6
"""

from __future__ import annotations

import pytest

from mcp_server.handlers.admission import DEFAULT_SEMAPHORE
from mcp_server.handlers.latency_class import (
    LatencyClass,
    _LATENCY_CLASS,
    classify,
)
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.pg_store import PgMemoryStore


@pytest.fixture
def store():
    s = PgMemoryStore()
    yield s
    s.close()


def _count_tools_by_class(cls: LatencyClass) -> int:
    """Count tools declared in the registry for a given class.

    Does not include heuristic-classified tools — those aren't known
    until runtime. Registry entries are the lower bound.
    """
    return sum(1 for v in _LATENCY_CLASS.values() if v == cls)


@pytest.mark.invariants
class TestI10PoolCapacity:
    """Pool capacity MUST accommodate concurrent cycle workers + 1."""

    def test_interactive_pool_max_size_covers_tool_fanout(self, store):
        """interactive_pool.max >= DEFAULT_SEMAPHORE[interactive] + 1.

        The semaphore bounds concurrent fan-out per tool; the pool
        must have at least that many connection slots plus one reserve
        so a fresh arrival is never starved by ongoing calls.
        """
        pool = store.interactive_pool
        budget = DEFAULT_SEMAPHORE["interactive"]
        assert pool.max_size >= budget + 1, (
            f"I10 violated: interactive_pool.max={pool.max_size} must be "
            f">= DEFAULT_SEMAPHORE[interactive]+1 = {budget + 1}"
        )

    def test_batch_pool_max_size_covers_cycle_fanout(self, store):
        """batch_pool.max >= DEFAULT_SEMAPHORE[batch] + 1.

        Even though batch tools run with Semaphore(1), the pool still
        needs a reserve slot so a consolidate mid-run does not block
        a subsequent wiki_pipeline from starting before consolidate
        finishes returning its connection.
        """
        pool = store.batch_pool
        budget = DEFAULT_SEMAPHORE["batch"]
        assert pool.max_size >= budget + 1, (
            f"I10 violated: batch_pool.max={pool.max_size} must be "
            f">= DEFAULT_SEMAPHORE[batch]+1 = {budget + 1}"
        )

    def test_interactive_pool_min_size_nonzero(self, store):
        """min >= 1 — always keep at least one warm connection on the
        hot path so the first request doesn't pay connect latency."""
        assert store.interactive_pool.min_size >= 1

    def test_pool_bounds_are_consistent(self, store):
        """min <= max for both pools."""
        ip = store.interactive_pool
        bp = store.batch_pool
        assert ip.min_size <= ip.max_size
        assert bp.min_size <= bp.max_size

    def test_settings_source_of_truth(self, store):
        """Pool sizes come from MemorySettings, not hard-coded."""
        settings = get_memory_settings()
        assert store.interactive_pool.max_size == settings.POOL_INTERACTIVE_MAX
        assert store.batch_pool.max_size == settings.POOL_BATCH_MAX


@pytest.mark.invariants
class TestI10RegistryCoverage:
    """Sanity checks on the latency-class registry that I10 depends on."""

    def test_at_least_one_interactive_tool(self):
        assert _count_tools_by_class("interactive") >= 1

    def test_at_least_one_batch_tool(self):
        assert _count_tools_by_class("batch") >= 1

    def test_critical_tools_registered(self):
        """The tools most likely to contend for the pool must be in the
        registry (not heuristic-classified) so we don't silently pick
        the wrong default."""
        assert classify("recall") == "interactive"
        assert classify("consolidate") == "batch"
        assert classify("wiki_reindex") == "batch"
        assert classify("ingest_codebase") == "batch"
