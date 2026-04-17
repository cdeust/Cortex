"""Phase 5 step 5: admission middleware tests.

Asserts:
    - admit() is a valid async context manager that serializes over budget
    - per-tool overrides take precedence over class defaults
    - class defaults (interactive=4, batch=1) apply when no override
    - reset_semaphores() clears the cache between tests

Source: docs/program/phase-5-pool-admission-design.md §1.4.
"""

from __future__ import annotations

import asyncio

import pytest

from mcp_server.handlers.admission import (
    admit,
    current_budget,
    reset_semaphores,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    reset_semaphores()
    yield
    reset_semaphores()


class TestBudgetResolution:
    def test_override_precedes_class_default(self):
        # recall has an override of 8
        assert current_budget("recall") == 8
        assert current_budget("memory_stats") == 8

    def test_interactive_class_default(self):
        # detect_gaps is interactive, no override → 4
        assert current_budget("detect_gaps") == 4

    def test_batch_class_default(self):
        # consolidate is batch, no override → 1
        assert current_budget("consolidate") == 1
        assert current_budget("seed_project") == 1

    def test_unknown_tool_via_heuristic(self):
        # Heuristic fallback: "something_ingest" → batch → 1
        assert current_budget("something_ingest") == 1
        # Unknown non-batch-named → interactive → 4
        assert current_budget("new_thing") == 4


class TestAdmitBehavior:
    @pytest.mark.asyncio
    async def test_admit_yields(self):
        async with admit("recall"):
            pass  # no-op — just exercises the context manager

    @pytest.mark.asyncio
    async def test_admit_concurrent_within_budget(self):
        """N concurrent admissions within budget all acquire immediately."""
        done = 0

        async def runner():
            nonlocal done
            async with admit("recall"):  # budget=8
                done += 1

        # 8 concurrent tasks — all fit
        await asyncio.gather(*(runner() for _ in range(8)))
        assert done == 8

    @pytest.mark.asyncio
    async def test_admit_batch_serializes(self):
        """batch tools with budget=1 serialize concurrent calls."""
        order: list[str] = []

        async def runner(label: str):
            async with admit("consolidate"):
                order.append(f"start-{label}")
                await asyncio.sleep(0.01)
                order.append(f"end-{label}")

        await asyncio.gather(runner("a"), runner("b"))
        # With budget=1, "a" completes before "b" starts.
        # Expected: [start-X, end-X, start-Y, end-Y] (either X=a or X=b).
        assert len(order) == 4
        first = order[0].split("-")[1]
        assert order == [
            f"start-{first}",
            f"end-{first}",
            f"start-{'b' if first == 'a' else 'a'}",
            f"end-{'b' if first == 'a' else 'a'}",
        ]

    @pytest.mark.asyncio
    async def test_admit_per_tool_independence(self):
        """Different tool names have independent semaphores."""
        recall_active = 0
        consolidate_active = 0
        max_recall = 0
        max_consolidate = 0

        async def recall_runner():
            nonlocal recall_active, max_recall
            async with admit("recall"):
                recall_active += 1
                max_recall = max(max_recall, recall_active)
                await asyncio.sleep(0.01)
                recall_active -= 1

        async def consolidate_runner():
            nonlocal consolidate_active, max_consolidate
            async with admit("consolidate"):
                consolidate_active += 1
                max_consolidate = max(max_consolidate, consolidate_active)
                await asyncio.sleep(0.01)
                consolidate_active -= 1

        # Mix: 4 recalls + 3 consolidates in parallel.
        await asyncio.gather(
            *(recall_runner() for _ in range(4)),
            *(consolidate_runner() for _ in range(3)),
        )
        # recall budget 8: all 4 concurrent
        # consolidate budget 1: max 1 concurrent
        assert max_recall == 4
        assert max_consolidate == 1
